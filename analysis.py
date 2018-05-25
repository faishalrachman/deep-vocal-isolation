import argparse
import datetime
import os
import numpy as np
from config import config
from keras.models import Model
from keras.layers import Input, Conv2D
from keras.initializers import Ones, Zeros
import h5py

import matplotlib
# The default tk backend does not work without X server
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import conversion  # noqa: E402
from chopper import Chopper  # noqa: E402
from acapellabot import AcapellaBot  # noqa: E402
from checkpointer import ErrorVisualization  # noqa: E402
from loss import Loss  # noqa: E402
from data import Data  # noqa: E402
from normalizer import Normalizer  # noqa: E402

BATCH_NORMALIZATIONINDEX = "batch_normalization_{}"
CONV2DINDEX = "conv2d_{}"

BATCH_LAYERS = 4
CONV2D_LAYERS = 12


class Analysis:
    def __init__(self):
        self.config = config
        self.analyse = "spectrograms"
        self.save = True
        self.analysisPath = self.config.analysis_path
        self.content = "Analyse {} \n"

    def get(self):
        return getattr(self, self.analyse)

    def run(self, analyse, save, args):
        self.analyse = analyse
        self.save = save
        self.content = self.content.format(self.analyse)
        config_str = str(self.config)
        print(config_str)

        print(self.content)
        analyse = self.get()
        analyse(*args)

    def slices(self, file, learnPhase="False"):
        self.config.learn_phase = eval(learnPhase)
        spectrogram = self._create_spectrogram_from_file(file)

        currMin = [float("inf"), float("inf")]
        currMinI = [-1, -1]
        currMax = [0, 0]
        currMaxI = [1, 1]
        meanDev = [0, 0]
        countDevSum = [0, 0]
        countDevMax = [0, 0]

        chop = Chopper().get(False)

        slices = chop(spectrogram)
        for i in range(0, len(slices)):

            if self.config.learn_phase:
                currMinI[0], currMin[0] = \
                    self._get_current_min(slices[i][:, :, 0],
                                          currMinI[0], currMin[0], i)
                currMaxI[0], currMax[0] = \
                    self._get_current_max(slices[i][:, :, 0],
                                          currMaxI[0], currMax[0], i)
                currMinI[1], currMin[1] = \
                    self._get_current_min(slices[i][:, :, 1],
                                          currMinI[1], currMin[1], i)
                currMaxI[1], currMax[1] = \
                    self._get_current_max(slices[i][:, :, 1],
                                          currMaxI[1], currMax[1], i)
            else:
                currMinI[0], currMin[0] = \
                    self._get_current_min(slices[i],
                                          currMinI[0], currMin[0], i)
                currMaxI[0], currMax[0] = \
                    self._get_current_max(slices[i],
                                          currMaxI[0], currMax[0], i)

        if self.config.learn_phase:
            s = np.array(slices)[:]
            meanDev[0] = np.sum(s[:, :, :, 0]) / \
                (len(slices) * np.prod(slices[0][:, :, 0].shape))
            meanDev[1] = np.sum(s[:, :, :, 1]) / \
                (len(slices) * np.prod(slices[0][:, :, 0].shape))
        else:
            meanDev[0] = np.sum(slices) / (len(slices) *
                                           np.prod(slices[0].shape))

        for slice in slices:
            if self.config.learn_phase:
                countDevSum[0] += self._get_count_dev_sum(slice[:, :, 0],
                                                          meanDev[0])
                countDevMax[0] += self._get_count_dev_max(slice[:, :, 0],
                                                          meanDev[0])
                countDevSum[1] += self._get_count_dev_sum(slice[:, :, 1],
                                                          meanDev[1])
                countDevMax[1] += self._get_count_dev_max(slice[:, :, 1],
                                                          meanDev[1])
            else:
                countDevSum[0] += self._get_count_dev_sum(slice, meanDev[0])
                countDevMax[0] += self._get_count_dev_max(slice, meanDev[0])

        self._write_slices_statistics(currMinI[0], currMin[0], currMaxI[0],
                                      currMax[0], meanDev[0],
                                      countDevSum[0], countDevMax[0],
                                      len(slices))
        if self.config.learn_phase:
            self._write("")
            self._write_slices_statistics(currMinI[1], currMin[1], currMaxI[1],
                                          currMax[1], meanDev[1],
                                          countDevSum[1], countDevMax[1],
                                          len(slices))

        self._save_analysis()

    def _get_count_dev_sum(self, slice, meanDev):
        if np.sum(slice) / np.prod(slice.shape) > meanDev:
            return 1
        else:
            return 0

    def _get_count_dev_max(self, slice, meanDev):
        if np.max(slice) > meanDev:
            return 1
        else:
            return 0

    def _get_current_min(self, spectrogram, currMinI, currMin, index):
        smin = np.min(spectrogram)

        if smin < currMin:
            return index, smin
        else:
            return currMinI, currMin

    def _get_current_max(self, spectrogram, currMaxI, currMax, index):
        smax = np.max(spectrogram)

        if smax > currMax:
            return index, smax
        else:
            return currMaxI, currMax

    def _write_slices_statistics(self, currMinI, currMin,
                                 currMaxI, currMax, meanDev,
                                 countDevSum, countDevMax, slicesLength):
        self._write("Minimum at %d with %f" % (currMinI, currMin))
        self._write("Maximum at %d with %f" % (currMaxI, currMax))
        self._write("Mean deviation %f" % meanDev)

        self._write("Count sum above mean deviation is %d of %d"
                    % (countDevSum, slicesLength))
        self._write("Count max above mean deviation is %d of %d"
                    % (countDevMax, slicesLength))

    def spectrograms(self, directory, learnPhase="False"):
        self.config.learn_phase = eval(learnPhase)

        data = self._read_spectrograms_from_dir(directory)

        counts = [[0, 0, 0], [0, 0, 0]]
        desc = ["upper", "center", "lower"]

        self._write("## Spectrogram analysis")

        if self.config.learn_phase:
            self._write("### Analysis for real and imaginary data")
            self._write("name | real/imag | best window | mean")
            self._write("-----|-----|-----|-----")
        else:
            self._write("### Analysis for amplitude data")
            self._write("name | best window | mean")
            self._write("-----|-----|-----")

        for (spectrogram, name) in data:
            if self.config.learn_phase:
                meansReal = self._calculate_spectrogram_windows(
                    spectrogram[:, :, 0])
                meansImag = self._calculate_spectrogram_windows(
                    spectrogram[:, :, 1])

                bestReal = np.argmax(meansReal)
                bestImag = np.argmax(meansImag)

                counts[0][bestReal] += 1
                counts[1][bestImag] += 1

                self._write("%s | real | %s | %f"
                            % (name, desc[bestReal], np.max(meansReal)))
                self._write("%s | imag | %s | %f"
                            % (name,  desc[bestImag], np.max(meansImag)))
            else:
                means = self._calculate_spectrogram_windows(spectrogram)

                best = np.argmax(means)
                counts[0][best] += 1

                self._write("%s | %s | %f" % (name, desc[best], np.max(means)))

        self._write("#### Statistics")

        if self.config.learn_phase:
            self._write("total | real/imag | upper | center | lower")
            self._write("-----|-----|-----|-----|-----")
            self._write("%d | real | %d | %d | %d"
                        % (len(data), counts[0][0],
                           counts[0][1], counts[0][2]))
            self._write("%d | imag | %d | %d | %d"
                        % (len(data), counts[1][0],
                           counts[1][1], counts[1][2]))
        else:
            self._write("total | upper | center | lower")
            self._write("-----|-----|-----|-----")
            self._write("%d | %d | %d | %d"
                        % (len(data), counts[0][0],
                           counts[0][1], counts[0][2]))

        self._save_analysis()

    def _calculate_spectrogram_windows(self, spectrogram):
        means = []
        window = spectrogram.shape[0] // 2
        upperWindow = spectrogram[0:window]
        means.append(np.sum(upperWindow) / np.prod(upperWindow.shape))
        centerWindow = spectrogram[window // 2: window // 2 + window]
        means.append(np.sum(centerWindow) / np.prod(centerWindow.shape))
        lowerWindow = spectrogram[-window:]
        means.append(np.sum(lowerWindow) / np.prod(lowerWindow.shape))

        return means

    def weights(self, directory):
        weights = self._read_weights_from_dir(directory)

        self._write("## Weights analysis")

        for i in range(0, len(weights) - 1):
            self._write("### Comparing weights of epoch %d with epoch %d"
                        % (i + 1, i + 2))

            betaDev, gammaDev, movingMeanDev, movingVarDev \
                = self._compare_batch_normalization(weights[i], weights[i + 1])
            biasDev, kernelDev \
                = self._compare_conv2d(weights[i], weights[i + 1])

            self._write("#### Statistics")
            self._write("##### Batch normalization")
            self._write("beta | gamma | moving mean | moving variance")
            self._write("-----|-----|-----|-----|-----")
            self._write("| %f | %f | %f | %f"
                        % (betaDev, gammaDev,
                           movingMeanDev, movingVarDev))
            self._write("##### Conv2D")
            self._write("bias | kernel")
            self._write("-----|-----|-----")

            self._write("%f | %f"
                        % (biasDev, kernelDev))

        self._save_analysis()

    # If the output is close to the input,
    # the naive solution would be to just pass the input through the network.
    # If the output is mostly close to 0,
    # then the naive solution would be to always return 0.
    #
    # Calculate the loss of these two naive solutions.
    # The real loss of the network should be below these values.
    def naive_solutions(self):
        data = Data()
        # use all data as validation data,
        # they have the right form to analyse
        data.trainingSplit = 0
        mashup, output = data.valid()

        channels = self.config.get_channels()

        input_layer = Input(shape=(None, None, channels), name='input')

        loss = Loss().get()

        # model with zero output
        conv0 = Conv2D(channels, 1, activation='linear',
                       kernel_initializer=Zeros(), padding='same')(input_layer)
        model0 = Model(inputs=input_layer, outputs=conv0)
        model0.compile(loss=loss, optimizer='adam')
        model0.summary(line_length=150)

        # model with output=input
        conv1 = Conv2D(channels, 1, activation='linear',
                       kernel_initializer=Ones(), padding='same')(input_layer)
        model1 = Model(inputs=input_layer, outputs=conv1)
        model1.compile(loss=loss, optimizer='adam')
        model1.summary(line_length=150)

        error0 = model0.evaluate(mashup, output, batch_size=8)
        error1 = model1.evaluate(mashup, output, batch_size=8)

        self._write("MSE for output=all_zeros: %f" % error0)
        self._write("MSE for output=input: %f" % error1)
        self._save_analysis()

    def _compare_batch_normalization(self, weight1, weight2):
        meanDevBeta = []
        meanDevGamma = []
        meanDevMovMean = []
        meanDevMovVar = []

        self._write("layer | beta | gamma | moving mean | moving variance")
        self._write("-----|-----|-----|-----|-----")

        for i in range(1, BATCH_LAYERS + 1):
            (beta1, gamma1, movingMean1, movingVariance1) \
                = self._get_batch_normalization_data(1, weight1)
            (beta2, gamma2, movingMean2, movingVariance2) \
                = self._get_batch_normalization_data(1, weight2)
            betaDiff = np.sum(abs(np.subtract(beta1, beta2))) / beta1.shape[0]
            gammaDiff = np.sum(abs(np.subtract(gamma1, gamma2))) \
                / gamma1.shape[0]
            movingMeanDiff \
                = np.sum(abs(np.subtract(movingMean1, movingMean2))) / \
                movingMean1.shape[0]
            movingVarianceDiff \
                = np.sum(abs(np.subtract(movingVariance1, movingVariance2))) \
                / movingVariance1.shape[0]
            meanDevBeta.append(betaDiff)
            meanDevGamma.append(gammaDiff)
            meanDevMovMean.append(movingMeanDiff)
            meanDevMovVar.append(movingVarianceDiff)
            self._write("batch normalization %d | %f | %f | %f | %f"
                        % ((i, betaDiff, gammaDiff,
                           movingMeanDiff, movingVarianceDiff)))

        betaDev = np.sum(meanDevBeta) / len(meanDevBeta)
        gammaDev = np.sum(meanDevGamma) / len(meanDevGamma)
        movingMeanDev = np.sum(meanDevMovMean) / len(meanDevMovMean)
        movingVarDev = np.sum(meanDevMovVar) / len(meanDevMovVar)

        return betaDev, gammaDev, movingMeanDev, movingVarDev

    def _compare_conv2d(self, weight1, weight2):
        meanDevBias = []
        meanDevKernel = []

        self._write("layer | bias | kernel")
        self._write("-----|-----|-----")

        for i in range(1, CONV2D_LAYERS + 1):
            (bias1, kernel1) = self._get_conv2d_layer_data(1, weight1)
            (bias2, kernel2) = self._get_conv2d_layer_data(1, weight2)
            biasDiff = np.sum(abs(np.subtract(bias1, bias2))) / bias1.shape[0]
            kernelDiff = np.sum(abs(np.subtract(kernel1, kernel2))) / \
                np.prod(kernel1.shape)
            meanDevBias.append(biasDiff)
            meanDevKernel.append(kernelDiff)

            self._write("conv2D %d | %f | %f"
                        % (i, biasDiff, kernelDiff))

        biasDev = np.sum(meanDevBias) / len(meanDevBias)
        kernelDev = np.sum(meanDevKernel) / len(meanDevKernel)

        return biasDev, kernelDev

    def _get_batch_normalization_data(self, number, weights):
        index = BATCH_NORMALIZATIONINDEX.format(number)
        tmp = weights[index][index]["beta:0"]
        beta = np.zeros(tmp.shape)
        tmp.read_direct(beta)
        tmp = weights[index][index]["gamma:0"]
        gamma = np.zeros(tmp.shape)
        tmp.read_direct(gamma)
        tmp = weights[index][index]["moving_mean:0"]
        movingMean = np.zeros(tmp.shape)
        tmp.read_direct(movingMean)
        tmp = weights[index][index]["moving_variance:0"]
        movingVariance = np.zeros(tmp.shape)
        tmp.read_direct(movingVariance)

        return beta, gamma, movingMean, movingVariance

    def _get_conv2d_layer_data(self, number, weights):
        index = CONV2DINDEX.format(number)
        tmp = weights[index][index]["bias:0"]
        bias = np.zeros(tmp.shape)
        tmp.read_direct(bias)
        tmp = weights[index][index]["kernel:0"]
        kernel = np.zeros(tmp.shape)
        tmp.read_direct(kernel)

        return bias, kernel

    def _print_h5_structure(self, weights):

        def print_name(name):
            print(name)

        weights.visit(print_name)

    def _read_weights_from_dir(self, directory):
        def check_filename(f):
            return (f.endswith(".h5") or f.endswith("hdf5")) \
                   and not f.startswith(".")

        weights = []

        for dirPath, dirNames, fileNames in os.walk(directory):
            filteredFiles = filter(check_filename, fileNames)

            for fileName in filteredFiles:
                path = os.path.join(directory, fileName)
                weight = h5py.File(path, "r")
                weights.append(weight)

        return weights

    def _read_spectrograms_from_dir(self, directory):
        def check_filename(f):
            return f.endswith(".wav") and not f.startswith(".")

        data = []

        for dirPath, dirNames, fileNames in os.walk(directory):
            filteredFiles = filter(check_filename, fileNames)

            for fileName in filteredFiles:
                path = os.path.join(directory, fileName)
                self._write("creating spectrogram for %s" % fileName, True)
                spectrogram = self._create_spectrogram_from_file(path)
                self._spectrogram_info(spectrogram)
                data.append((spectrogram, fileName))

        return data

    def _create_spectrogram_from_file(self, filePath):
        audio, sampleRate = conversion.loadAudioFile(filePath)
        spectrogram = \
            conversion.audioFileToSpectrogram(audio, 1536,
                                              self.config.learn_phase)

        return spectrogram

    def error_images(self):
        acapellabot = AcapellaBot(self.config)
        acapellabot.loadWeights(self.config.weights)

        data = Data()
        xValid, yValid = data.valid()
        acapellabot.xValid, acapellabot.yValid = xValid, yValid

        error_visualization = ErrorVisualization(acapellabot)
        error_visualization.on_epoch_end(-1)

    def _write(self, message, printAnyway=False):
        if self.save:
            self.content += "\n" + message
            if printAnyway:
                print(message)
        else:
            print(message)

    def _save_analysis(self):
        print("\nAnalysis complete")
        if self.save:
            date = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
            if not os.path.exists(self.analysisPath):
                os.makedirs(self.analysisPath)

            path = self.analysisPath + "/" + self.analyse + date + ".txt"
            with open(path, "w") as f:
                f.write(self.content)

    def _spectrogram_info(self, spectrogram):
        if self.config.learn_phase:
            self._write("Range of the real part is " +
                        str(np.min(spectrogram[:, :, 0])) + " -> " +
                        str(np.max(spectrogram[:, :, 0])))
            self._write("Range of the imag part is " +
                        str(np.min(spectrogram[:, :, 1])) + " -> " +
                        str(np.max(spectrogram[:, :, 1])))
        else:
            self._write("Range of spectrogram is " +
                        str(np.min(spectrogram)) + " -> " +
                        str(np.max(spectrogram)))
        image = np.clip((spectrogram - np.min(spectrogram)) /
                        (np.max(spectrogram) - np.min(spectrogram)), 0, 1)
        self._write("Shape of spectrogram is (%d, %d, %d)"
                    % (image.shape[0], image.shape[1],
                       self.config.get_channels()))

    def chopper(self, file, chopparams=None, learnPhase="False"):
        self.config.learn_phase = eval(learnPhase)

        spectrogram = self._create_spectrogram_from_file(file)
        self._spectrogram_info(spectrogram)

        chopNames = Chopper().get_all_chop_names()

        if chopparams is not None:
            if isinstance(eval(chopparams), dict):
                params = chopparams
            else:
                params = self.config.chopparams
        else:
            params = self.config.chopparams

        params = eval(params)

        params['upper'] = False
        self.config.chopparams = str(params)

        self._write("## Chopper analysis")
        self._write("\nchop params: " + self.config.chopparams + "\n", True)
        self._write("name | slices created "
                    "| first slice shape | last slice shape")
        self._write("-----|-----|-----|-----")

        for name in chopNames:
            self.config.chopname = name
            chop = Chopper().get()
            mashupSlices, acapellaSlices = chop(spectrogram, spectrogram)
            self._write("%s | %d | %s | %s"
                        % (self.config.chopname, len(mashupSlices),
                           (mashupSlices[0].shape,),
                           (mashupSlices[-1].shape,)))

        params['upper'] = True
        self.config.chopparams = str(params)
        self._write("\nchop params: " + self.config.chopparams + "\n", True)
        self._write("name | slices created "
                    "| first slice shape | last slice shape")
        self._write("-----|-----|-----|-----")

        for name in chopNames:
            self.config.chopname = name
            chop = Chopper().get()
            mashupSlices, acapellaSlices = chop(spectrogram, spectrogram)
            self._write("%s | %d | %s | %s"
                        % (self.config.chopname, len(mashupSlices),
                           (mashupSlices[0].shape,),
                           (mashupSlices[-1].shape,)))

        self._save_analysis()

    def normalizer(self, file, learnPhase=False):
        self.config.learn_phase = eval(learnPhase)
        spectrogram = self._create_spectrogram_from_file(file)
        self._spectrogram_info(spectrogram)

        self.config.normalizer = "percentile"
        self.config.normalizer_params = "{'percentile': 95}"
        normalizer = Normalizer()
        normalize = normalizer.get(both=False)
        denormalize = normalizer.get_reverse()

        minS = [0, 0]
        maxS = [0, 0]
        meanS = [0, 0]
        perc = [0, 0]

        percentile = eval(self.config.normalizer_params)['percentile']
        if self.config.learn_phase:
            self._write("form | real/imag | percentile "
                        "| minimum | maximum | mean")
            self._write("-----|-----|-----|-----|-----|-----")

            minS[0] = np.min(spectrogram[:, :, 0])
            maxS[0] = np.max(spectrogram[:, :, 0])
            meanS[0] = np.mean(spectrogram[:, :, 0])
            perc[0] = np.percentile(spectrogram[:, :, 0], percentile)

            minS[1] = np.min(spectrogram[:, :, 1])
            maxS[1] = np.max(spectrogram[:, :, 1])
            meanS[1] = np.mean(spectrogram[:, :, 1])
            perc[1] = np.percentile(spectrogram[:, :, 1], percentile)

            self._write("original | real | %d | %f | %f | %f"
                        % (percentile, minS[0], maxS[0], meanS[0]))
            self._write("original | imag | %d | %f | %f | %f"
                        % (percentile, minS[1], maxS[1], meanS[1]))

            spectrogram, norm = normalize(spectrogram)

            minS[0] = np.min(spectrogram[:, :, 0])
            maxS[0] = np.max(spectrogram[:, :, 0])
            meanS[0] = np.mean(spectrogram[:, :, 0])
            perc[0] = np.percentile(spectrogram[:, :, 0], percentile)

            minS[1] = np.min(spectrogram[:, :, 1])
            maxS[1] = np.max(spectrogram[:, :, 1])
            meanS[1] = np.mean(spectrogram[:, :, 1])
            perc[1] = np.percentile(spectrogram[:, :, 1], percentile)

            self._write("normalized | real | %d | %f | %f | %f"
                        % (percentile, minS[0], maxS[0], meanS[0]))
            self._write("normalized | imag | %d | %f | %f | %f" %
                        (percentile, minS[1], maxS[1], meanS[1]))

            spectrogram = denormalize(spectrogram, norm)

            minS[0] = np.min(spectrogram[:, :, 0])
            maxS[0] = np.max(spectrogram[:, :, 0])
            meanS[0] = np.mean(spectrogram[:, :, 0])
            perc[0] = np.percentile(spectrogram[:, :, 0], percentile)

            minS[1] = np.min(spectrogram[:, :, 1])
            maxS[1] = np.max(spectrogram[:, :, 1])
            perc[1] = np.percentile(spectrogram[:, :, 1], percentile)

            self._write("denormalized | real | %d | %f | %f | %f"
                        % (percentile, minS[0], maxS[0], meanS[0]))
            self._write("denormalized | imag | %d | %f | %f | %f"
                        % (percentile, minS[1], maxS[1], meanS[1]))

        else:
            self._write("form | percentile | minimum | maximum | mean")
            self._write("-----|-----|-----|-----|-----")

            minS[0] = np.min(spectrogram)
            maxS[0] = np.max(spectrogram)
            meanS[0] = np.mean(spectrogram)
            perc[0] = np.percentile(spectrogram[:, :, 0], percentile)

            self._write("original | %d | %f | %f | %f"
                        % (percentile, minS[0], maxS[0], meanS[0]))

            spectrogram, norm = normalize(spectrogram)

            minS[0] = np.min(spectrogram)
            maxS[0] = np.max(spectrogram)
            meanS[0] = np.mean(spectrogram)
            perc[0] = np.percentile(spectrogram[:, :, 0], percentile)

            self._write("normalized | %d | %f | %f | %f"
                        % (percentile, minS[0], maxS[0], meanS[0]))

            spectrogram = denormalize(spectrogram, norm)

            minS[0] = np.min(spectrogram)
            maxS[0] = np.max(spectrogram)
            meanS[0] = np.mean(spectrogram)
            perc[0] = np.percentile(spectrogram[:, :, 0], percentile)

            self._write("denormalized | %d | %f | %f | %f"
                        % (percentile, minS[0], maxS[0], meanS[0]))

        self._save_analysis()

    def _get_histogram_prepare(self, data, normalize):
        def _histogram_prepare(track):
            track = data.prepare_spectrogram(track)
            track, _ = normalize(track)
            track = track.flatten()
            return track
        return _histogram_prepare

    def _do_histogram(self, data, spectrograms, name):
        normalize = Normalizer().get(both=False)
        prepare = self._get_histogram_prepare(data, normalize)
        values = np.array([])
        for track in data.track_names:
            t = prepare(spectrograms[track])
            values = np.append(values, t)

        n, _, _ = plt.hist(np.abs(values), bins='auto',
                           log=True, cumulative=-1)
        print(name)
        print(list(n/max(n)))
        if not os.path.exists(self.analysisPath):
            os.mkdir(self.analysisPath)
        plt.savefig(os.path.join(self.analysisPath, "%s_hist.png" % name))
        plt.close()

        del values

    def histogram(self):
        data = Data()

        self._do_histogram(data, data.mashup, "Mashup")
        self._do_histogram(data, data.instrumental, "Instrumental")
        self._do_histogram(data, data.acapella, "Acapella")

    def percentile(self):
        data = Data()

        self._do_percentile(data, data.mashup, "Mashup")
        self._do_percentile(data, data.instrumental, "Instrumental")
        self._do_percentile(data, data.acapella, "Acapella")

    def _do_percentile(self, data, spectrograms, name):

        pbar = None
        try:
            from progressbar import ProgressBar, Percentage, Bar
            pbar = ProgressBar(widgets=[Percentage(), Bar()],
                               maxval=len(data.track_names)*101)
            pbar.start()
        except Exception as e:
            pass

        k = 0
        if config.learn_phase:
            y_real = [[] for _ in range(101)]
            y_imag = [[] for _ in range(101)]
            for track in sorted(data.track_names):
                t = data.prepare_spectrogram(spectrograms[track])
                median_real = np.median(t[:, :, 0])
                median_imag = np.median(t[:, :, 1])
                for i in range(101):
                    if pbar is not None:
                        pbar.update(k)
                    k += 1
                    v = np.percentile(t[:, :, 0], i)
                    y_real[i].append(v-median_real)

                    v = np.percentile(t[:, :, 1], i)
                    y_imag[i].append(v-median_imag)

            h5f = h5py.File("ir-percentile-%s.hdf5" % name, "w")
            h5f.create_dataset(name="real",
                               data=y_real)
            h5f.create_dataset(name="imag",
                               data=y_imag)
            h5f.close()

            plt.figure(figsize=(15, 15))
            plt.subplot(211)
            result = plt.boxplot(y_real, labels=range(101))
            print([l.get_ydata()[0] for l in result["medians"]])
            plt.xticks(rotation=90)
            plt.title("Real")
            plt.xlabel("percentile")
            plt.ylabel("difference from median")

            plt.subplot(212)
            result = plt.boxplot(y_imag, labels=range(101))
            print([l.get_ydata()[0] for l in result["medians"]])
            plt.xticks(rotation=90)
            plt.title("Imag")
            plt.xlabel("percentile")
            plt.ylabel("difference from median")
            if not os.path.exists(self.analysisPath):
                os.mkdir(self.analysisPath)
            plt.savefig(os.path.join(self.analysisPath,
                                     "percentile_%s_ir.png" % name))
            plt.close()
        else:
            y = [[] for _ in range(101)]
            for track in data.track_names:
                t = data.prepare_spectrogram(spectrograms[track])
                median = np.median(t)
                for i in range(101):
                    if pbar is not None:
                        pbar.update(k)
                    k += 1
                    v = np.percentile(t, i)
                    y[i].append(v-median)

            h5f = h5py.File("amp-percentile-%s.hdf5" % name, "w")
            h5f.create_dataset(name="value",
                               data=y)
            h5f.close()

            plt.figure(figsize=(15, 15))
            result = plt.boxplot(y, labels=range(101))
            print([l.get_ydata()[0] for l in result["medians"]])
            plt.xticks(rotation=90)
            plt.title("Amplitude")
            plt.xlabel("percentile")
            plt.ylabel("difference from median")
            if not os.path.exists(self.analysisPath):
                os.mkdir(self.analysisPath)
            plt.savefig(os.path.join(self.analysisPath,
                                     "percentile_%s_amplitude.png" % name))
            plt.close()

    def stoi(self, filepath, clean_filepath=None):
        # filepath = path to mashup
        # Needs octave and octave-signal installed
        # Use "pip install oct2py" to install python - octave bridge
        # STOI assumes
        # * a sampling rate of 10kHz, resamples otherwise
        # * window length of 384ms
        # * 15 third octave bands over full frequency range
        # * overlapping segments with hanning window
        # * removes silent frames
        import librosa
        from oct2py import octave
        if clean_filepath is None:
            # No clean file given.
            # Get processed and clean file from mashup.
            acapellabot = AcapellaBot(config)
            acapellabot.loadWeights(config.weights)
            audio, sampleRate = conversion.loadAudioFile(filepath)
            spectrogram = conversion.audioFileToSpectrogram(
                audio, fftWindowSize=config.fft,
                learn_phase=self.config.learn_phase)

            normalizer = Normalizer()
            normalize = normalizer.get(both=False)
            denormalize = normalizer.get_reverse()

            # normalize
            spectogram, norm = normalize(spectrogram)

            info = acapellabot.process_spectrogram(spectrogram,
                                                   config.get_channels())
            spectrogram, newSpectrogram = info
            # de-normalize
            newSpectrogram = denormalize(newSpectrogram, norm)

            processed = conversion.spectrogramToAudioFile(newSpectrogram,
                                                          config.fft,
                                                          config.phase)

            clean_filepath = filepath.replace("_all.wav", "_acapella.wav")
            clean, sampling_rate = librosa.load(clean_filepath)
        else:
            # A clean file is given.
            # Compare it with the processed audio.
            processed, sampling_rate = librosa.load(filepath)
            clean, sampling_rate = librosa.load(clean_filepath)

        # Make sure the original and processed audio have the same length
        clean = clean[:processed.shape[0]]

        octave.eval("pkg load signal")
        d = octave.stoi(clean, processed, sampling_rate)
        self._write("stoi: %f" % d)

    def mse(self, processed=None, vocal=None):
        self.mean_squared_error(processed, vocal)

    def mean_squared_error(self, processed_file=None, vocal_file=None):
        normalizer = Normalizer()
        normalize = normalizer.get(both=False)
        if processed_file is None:
            acapellabot = AcapellaBot(config)
            acapellabot.loadWeights(config.weights)
            data = Data()
            mses = []
            for track in data.validation_tracks + data.test_tracks:
                mashup = data.prepare_spectrogram(data.mashup[track])
                vocal = data.prepare_spectrogram(data.acapella[track])
                mashup, norm = normalize(mashup)
                vocal, _ = normalize(vocal, norm)
                info = acapellabot.process_spectrogram(mashup,
                                                       config.get_channels())
                newSpectrogram = info[1]
                mse = ((newSpectrogram - vocal)**2).mean()
                mses.append(mse)
                print(track, mse)
            print(np.mean(mses))
        else:
            vocal_audio, _ = conversion.loadAudioFile(vocal_file)
            processed_audio, _ = conversion.loadAudioFile(processed_file)

            # make sure audios have the same length
            vocal_audio = vocal_audio[:processed_audio.shape[0]]
            processed_audio = processed_audio[:vocal_audio.shape[0]]

            wave_mse = ((vocal_audio - processed_audio)**2).mean()

            print("\n")
            self._write("Wave mean squared error: %s" % wave_mse)

    def volume(self, filepath):
        normalizer = Normalizer()
        normalize = normalizer.get(both=False)
        denormalize = normalizer.get_reverse()

        vocal_file = filepath.replace("_all.wav", "_acapella.wav")
        instrumental_file = filepath.replace("_all.wav", "_instrumental.wav")

        acapellabot = AcapellaBot(config)
        acapellabot.loadWeights(config.weights)

        instrumental_audio, _ = conversion.loadAudioFile(instrumental_file)
        vocal_audio, _ = conversion.loadAudioFile(vocal_file)

        instrumental = conversion.audioFileToSpectrogram(
            instrumental_audio, fftWindowSize=config.fft,
            learn_phase=self.config.learn_phase)
        vocal = conversion.audioFileToSpectrogram(
            vocal_audio, fftWindowSize=config.fft,
            learn_phase=self.config.learn_phase)
        h5file = h5py.File("volume.hdf5", "w")

        ratio = 100
        x = [i/ratio for i in range(1, ratio)] + \
            [1] + \
            [ratio/i for i in range(ratio-1, 0, -1)]
        h5file.create_dataset(name="x", data=x)

        print("Unscaled original mix")
        mashup, norm = normalize(instrumental + vocal)
        acapella, _ = normalize(vocal, norm)
        info = acapellabot.process_spectrogram(mashup,
                                               config.get_channels())
        newSpectrogram = denormalize(info[1], norm)
        mse = ((newSpectrogram - vocal)**2).mean()
        y = [mse for _ in x]
        plt.loglog(x, y, label="baseline")
        h5file.create_dataset(name="baseline", data=y)

        original_ratio = np.max(vocal)/np.max(instrumental)
        print("Original ratio: %s" % original_ratio)
        vocal /= original_ratio

        print("Change vocal volume")
        y = []
        for i in x:
            mashup, norm = normalize(instrumental + i * vocal)
            acapella, _ = normalize(i * vocal, norm)
            info = acapellabot.process_spectrogram(mashup,
                                                   config.get_channels())
            newSpectrogram = denormalize(info[1], norm)
            if i != 0:
                newSpectrogram = newSpectrogram / i

            mse = ((newSpectrogram - vocal)**2).mean()
            y.append(mse)
            print(mse)
        plt.loglog(x, y, label="scaled")

        plt.xlabel("vocal/instrumental")
        plt.ylabel("mean squared error")
        plt.legend()

        h5file.create_dataset(name="scale", data=y)
        h5file.close()
        if not os.path.exists(self.analysisPath):
            os.mkdir(self.analysisPath)
        plt.savefig(os.path.join(self.analysisPath, "volume.png"))

    def distribution(self):
        data = Data()

        self._do_distribution(data, data.mashup, "Mashup")
        self._do_distribution(data, data.instrumental, "Instrumental")
        self._do_distribution(data, data.acapella, "Acapella")

    def _do_distribution_plot(self, pbar, h5f, data, spectrograms,
                              bin_range, part, prefix=""):
        k = 0
        vals = []
        for track in sorted(data.track_names):
            spectrogram = data.prepare_spectrogram(spectrograms[track])
            if pbar is not None:
                pbar.update(k)
            k += 1

            channel = 0
            if prefix == "imag":
                channel = 1

            window = spectrogram.shape[0] // 2
            if part == "upper":
                window_values = spectrogram[0:window, :, channel]
            elif part == "center":
                window_values = spectrogram[window // 2: window // 2 + window, :, channel]  # noqa
            else:
                window_values = spectrogram[-window:, :, channel]
            vals += window_values[:, :].flatten().tolist()

        if bin_range is None:
            if config.learn_phase:
                bin_min = np.percentile(vals, 1)
            else:
                bin_min = 0
            bin_max = np.percentile(vals, 99)
            bin_range = (bin_min, bin_max)

        values, bins, patches = plt.hist(vals,
                                         range=bin_range,
                                         bins=25,
                                         label="%s %s" % (prefix, part))
        plt.legend()
        h5f.create_dataset(name="%s_values" % part, data=values)
        h5f.create_dataset(name="%s_bins" % part, data=bins)
        del vals
        return bin_range

    def _do_distribution(self, data, spectrograms, name):

        pbar = None
        try:
            from progressbar import ProgressBar, Percentage, Bar
            pbar = ProgressBar(widgets=[Percentage(), Bar()],
                               maxval=len(data.track_names))
            pbar.start()
        except Exception as e:
            pass

        if config.learn_phase:
            h5file = h5py.File("distribution_ir_%s.hdf5" % name, "w")
            h5real = h5file.create_group("real")
            h5imag = h5file.create_group("imag")

            plt.figure(figsize=(15, 15))
            plt.suptitle(name)
            ax1 = plt.subplot(231)
            bins = self._do_distribution_plot(pbar, h5real, data, spectrograms,
                                              None, "upper", "real")

            plt.subplot(232, sharey=ax1, sharex=ax1)
            self._do_distribution_plot(pbar, h5real, data, spectrograms,
                                       bins, "center", "real")

            plt.subplot(233, sharey=ax1, sharex=ax1)
            self._do_distribution_plot(pbar, h5real, data, spectrograms,
                                       bins, "lower", "real")

            ax1 = plt.subplot(234)
            bins = self._do_distribution_plot(pbar, h5imag, data, spectrograms,
                                              None, "upper", "imag")

            plt.subplot(235, sharey=ax1, sharex=ax1)
            self._do_distribution_plot(pbar, h5imag, data, spectrograms,
                                       bins, "center", "imag")

            plt.subplot(236, sharey=ax1, sharex=ax1)
            self._do_distribution_plot(pbar, h5imag, data, spectrograms,
                                       bins, "lower", "imag")

            h5file.close()

            if not os.path.exists(self.analysisPath):
                os.mkdir(self.analysisPath)
            plt.savefig(os.path.join(self.analysisPath,
                                     "distribution_%s_ir.png" % name))
            plt.close()
        else:
            h5file = h5py.File("distribution_amplitude_%s.hdf5" % name, "w")

            plt.figure(figsize=(15, 15))
            plt.suptitle(name)
            ax1 = plt.subplot(131)
            bins = self._do_distribution_plot(pbar, h5file, data, spectrograms,
                                              None, "upper")

            plt.subplot(132, sharey=ax1, sharex=ax1)
            self._do_distribution_plot(pbar, h5file, data, spectrograms,
                                       bins, "center")

            plt.subplot(133, sharey=ax1, sharex=ax1)
            self._do_distribution_plot(pbar, h5file, data, spectrograms,
                                       bins, "lower")
            h5file.close()

            if not os.path.exists(self.analysisPath):
                os.mkdir(self.analysisPath)
            plt.savefig(os.path.join(self.analysisPath,
                                     "distribution_%s_amplitude.png" % name))
            plt.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyse", "-a", default=None, type=str,
                        help="analysis to be executed")
    parser.add_argument("--save", "-s", action='store_true',
                        help="save analysis output to file")
    parser.add_argument("args", nargs="*", default=[])

    arguments = parser.parse_args()

    analysis = Analysis()
    analysis.run(arguments.analyse, arguments.save, arguments.args)
