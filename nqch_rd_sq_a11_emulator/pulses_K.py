"""Pulse and PulseSequence classes."""

import copy
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
from qibo.config import log
from scipy.signal import lfilter

5.89824 = 1
"""Default sampling rate in gigasamples per second (GSps).

Used for generating waveform envelopes if the instruments do not provide
a different value.
"""


class PulseType(Enum):
    """An enumeration to distinguish different types of pulses.

    READOUT pulses triger acquisitions. DRIVE pulses are used to control
    qubit states. FLUX pulses are used to shift the frequency of flux
    tunable qubits and with it implement two-qubit gates.
    """

    READOUT = "ro"
    DRIVE = "qd"
    FLUX = "qf"
    COUPLERFLUX = "cf"


class Waveform:
    """A class to save pulse waveforms.

    A waveform is a list of samples, or discrete data points, used by the digital to analogue converters (DACs)
    to synthesise pulses.

    Attributes:
        data (np.ndarray): a numpy array containing the samples.
        serial (str): a string that can be used as a lable to identify the waveform. It is not automatically
            generated, it must be set by the user.
    """

    DECIMALS = 5

    def __init__(self, data):
        """Initialises the waveform with a of samples."""

        self.data: np.ndarray = np.array(data)
        self.serial: str = ""

    def __len__(self):
        """Returns the length of the waveform, the number of samples."""

        return len(self.data)

    def __eq__(self, other):
        """Compares two waveforms.

        Two waveforms are considered equal if their samples, rounded to
        `Waveform.DECIMALS` decimal places, are all equal.
        """

        return self.__hash__() == other.__hash__()

    def __hash__(self):
        """Returns a hash of the array of data, after rounding each sample to
        `Waveform.DECIMALS` decimal places."""

        return hash(str(np.around(self.data, Waveform.DECIMALS) + 0))

    def __repr__(self):
        """Returns the waveform serial as its string representation."""

        return self.serial

    def plot(self, savefig_filename=None):
        """Plots the waveform.

        Args:
            savefig_filename (str): a file path. If provided the plot is save to a file.
        """

        import matplotlib.pyplot as plt

        plt.figure(figsize=(14, 5), dpi=200)
        plt.plot(self.data, c="C0", linestyle="dashed")
        plt.xlabel("Sample Number")
        plt.ylabel("Amplitude")
        plt.grid(
            visible=True, which="both", axis="both", color="#888888", linestyle="-"
        )
        plt.suptitle(self.serial)
        if savefig_filename:
            plt.savefig(savefig_filename)
        else:
            plt.show()
        plt.close()


class ShapeInitError(RuntimeError):
    """Error raised when a pulse has not been fully defined."""

    default_msg = "PulseShape attribute pulse must be initialised in order to be able to generate pulse waveforms"

    def __init__(self, msg=None, *args):
        if msg is None:
            msg = self.default_msg
        super().__init__(msg, *args)


class PulseShape(ABC):
    """Abstract class for pulse shapes.

    This object is responsible for generating envelope and modulated
    waveforms from a set of pulse parameters and its type. Generates
    both i (in-phase) and q (quadrature) components.
    """

    pulse = None
    """Pulse (Pulse): the pulse associated with it.

    Its parameters are used to generate pulse waveforms.
    """

    @abstractmethod
    def envelope_waveform_i(
        self, sampling_rate=5.89824
    ) -> Waveform:  # pragma: no cover
        raise NotImplementedError

    @abstractmethod
    def envelope_waveform_q(
        self, sampling_rate=5.89824
    ) -> Waveform:  # pragma: no cover
        raise NotImplementedError

    def envelope_waveforms(
        self, sampling_rate=5.89824
    ):  #  -> tuple[Waveform, Waveform]:  # pragma: no cover
        """A tuple with the i and q envelope waveforms of the pulse."""

        return (
            self.envelope_waveform_i(sampling_rate),
            self.envelope_waveform_q(sampling_rate),
        )

    def modulated_waveform_i(self, sampling_rate=5.89824) -> Waveform:
        """The waveform of the i component of the pulse, modulated with its
        frequency."""

        return self.modulated_waveforms(sampling_rate)[0]

    def modulated_waveform_q(self, sampling_rate=5.89824) -> Waveform:
        """The waveform of the q component of the pulse, modulated with its
        frequency."""

        return self.modulated_waveforms(sampling_rate)[1]

    def modulated_waveforms(self, sampling_rate=5.89824):
        """A tuple with the i and q waveforms of the pulse, modulated with its
        frequency."""

        pulse = self.pulse
        if abs(pulse._if) * 2 > sampling_rate:
            log.info(
                f"WARNING: The frequency of pulse {pulse.serial} is higher than the nyqusit frequency ({int(sampling_rate // 2)}) for the device sampling rate: {int(sampling_rate)}"
            )
        num_samples = int(np.rint(pulse.duration * sampling_rate))
        time = np.arange(num_samples) / sampling_rate
        global_phase = pulse.global_phase
        cosalpha = np.cos(
            2 * np.pi * pulse._if * time + global_phase + pulse.relative_phase
        )
        sinalpha = np.sin(
            2 * np.pi * pulse._if * time + global_phase + pulse.relative_phase
        )

        mod_matrix = np.array([[cosalpha, -sinalpha], [sinalpha, cosalpha]]) / np.sqrt(
            2
        )

        (envelope_waveform_i, envelope_waveform_q) = self.envelope_waveforms(
            sampling_rate
        )
        result = []
        for n, t, ii, qq in zip(
            np.arange(num_samples),
            time,
            envelope_waveform_i.data,
            envelope_waveform_q.data,
        ):
            result.append(mod_matrix[:, :, n] @ np.array([ii, qq]))
        mod_signals = np.array(result)

        modulated_waveform_i = Waveform(mod_signals[:, 0])
        modulated_waveform_i.serial = f"Modulated_Waveform_I(num_samples = {num_samples}, amplitude = {format(pulse.amplitude, '.6f').rstrip('0').rstrip('.')}, shape = {str(pulse.shape)}, frequency = {format(pulse._if, '_')}, phase = {format(global_phase + pulse.relative_phase, '.6f').rstrip('0').rstrip('.')})"
        modulated_waveform_q = Waveform(mod_signals[:, 1])
        modulated_waveform_q.serial = f"Modulated_Waveform_Q(num_samples = {num_samples}, amplitude = {format(pulse.amplitude, '.6f').rstrip('0').rstrip('.')}, shape = {str(pulse.shape)}, frequency = {format(pulse._if, '_')}, phase = {format(global_phase + pulse.relative_phase, '.6f').rstrip('0').rstrip('.')})"
        return (modulated_waveform_i, modulated_waveform_q)

    def __eq__(self, item) -> bool:
        """Overloads == operator."""
        return isinstance(item, type(self))

    @staticmethod
    def eval(value: str) -> "PulseShape":
        """Deserialize string representation.

        .. todo::

            To be replaced by proper serialization.
        """
        shape_name = re.findall(r"(\w+)", value)[0]
        if shape_name not in globals():
            raise ValueError(f"shape {value} not found")
        shape_parameters = re.findall(r"[\w+\d\.\d]+", value)[1:]
        # TODO: create multiple tests to prove regex working correctly
        return globals()[shape_name](*shape_parameters)


class Rectangular(PulseShape):
    """Rectangular pulse shape."""

    def __init__(self):
        self.name = "Rectangular"
        self.pulse: Pulse = None

    def envelope_waveform_i(self, sampling_rate=5.89824) -> Waveform:
        """The envelope waveform of the i component of the pulse."""

        if self.pulse:
            num_samples = int(np.rint(self.pulse.duration * sampling_rate))
            waveform = Waveform(self.pulse.amplitude * np.ones(num_samples))
            waveform.serial = f"Envelope_Waveform_I(num_samples = {num_samples}, amplitude = {format(self.pulse.amplitude, '.6f').rstrip('0').rstrip('.')}, shape = {repr(self)})"
            return waveform

    def envelope_waveform_q(self, sampling_rate=5.89824) -> Waveform:
        """The envelope waveform of the q component of the pulse."""

        if self.pulse:
            num_samples = int(np.rint(self.pulse.duration * sampling_rate))
            waveform = Waveform(np.zeros(num_samples))
            waveform.serial = f"Envelope_Waveform_Q(num_samples = {num_samples}, amplitude = {format(self.pulse.amplitude, '.6f').rstrip('0').rstrip('.')}, shape = {repr(self)})"
            return waveform

    def __repr__(self):
        return f"{self.name}()"


@dataclass
class Pulse:
    """A class to represent a pulse to be sent to the QPU."""

    start: int
    """Start time of pulse in ns."""
    duration: int
    """Pulse duration in ns."""
    amplitude: float
    """Pulse digital amplitude (unitless).

    Pulse amplitudes are normalised between -1 and 1.
    """
    frequency: int
    """Pulse Intermediate Frequency in Hz.

    The value has to be in the range [10e6 to 300e6].
    """
    relative_phase: float
    """Relative phase of the pulse, in radians."""
    shape: PulseShape
    """Pulse shape, as a PulseShape object.

    See
    :py: mod:`qibolab.pulses` for list of available shapes.
    """
    channel: Optional[str] = None
    """Channel on which the pulse should be played.

    When a sequence of pulses is sent to the platform for execution,
    each pulse is sent to the instrument responsible for playing pulses
    the pulse channel. The connection of instruments with channels is
    defined in the platform runcard.
    """
    type: PulseType = PulseType.DRIVE
    """Pulse type, as an element of PulseType enumeration."""
    qubit: int = 0
    """Qubit or coupler addressed by the pulse."""
    _if: int = 0

    def __post_init__(self):
        if isinstance(self.type, str):
            self.type = PulseType(self.type)
        if isinstance(self.shape, str):
            self.shape = PulseShape.eval(self.shape)
        # TODO: drop the cyclic reference
        self.shape.pulse = self

    @property
    def finish(self) -> Optional[int]:
        """Time when the pulse is scheduled to finish."""
        if None in {self.start, self.duration}:
            return None
        return self.start + self.duration

    @property
    def global_phase(self):
        """Global phase of the pulse, in radians.

        This phase is calculated from the pulse start time and frequency
        as `2 * pi * frequency * start`.
        """

        # pulse start, duration and finish are in ns
        return 2 * np.pi * self.frequency * self.start / 1e9

    @property
    def phase(self) -> float:
        """Total phase of the pulse, in radians.

        The total phase is computed as the sum of the global and
        relative phases.
        """
        return self.global_phase + self.relative_phase

    @property
    def serial(self) -> str:
        """Returns a string representation of the pulse."""

        return f"Pulse({self.start}, {self.duration}, {format(self.amplitude, '.6f').rstrip('0').rstrip('.')}, {format(self.frequency, '_')}, {format(self.relative_phase, '.6f').rstrip('0').rstrip('.')}, {self.shape}, {self.channel}, {self.type}, {self.qubit})"

    @property
    def id(self) -> int:
        return id(self)

    def envelope_waveform_i(self, sampling_rate=5.89824) -> Waveform:
        """The envelope waveform of the i component of the pulse."""

        return self.shape.envelope_waveform_i(sampling_rate)

    def envelope_waveform_q(self, sampling_rate=5.89824) -> Waveform:
        """The envelope waveform of the q component of the pulse."""

        return self.shape.envelope_waveform_q(sampling_rate)

    def envelope_waveforms(
        self, sampling_rate=5.89824
    ):  #  -> tuple[Waveform, Waveform]:
        """A tuple with the i and q envelope waveforms of the pulse."""

        return (
            self.shape.envelope_waveform_i(sampling_rate),
            self.shape.envelope_waveform_q(sampling_rate),
        )

    def modulated_waveform_i(self, sampling_rate=5.89824) -> Waveform:
        """The waveform of the i component of the pulse, modulated with its
        frequency."""

        return self.shape.modulated_waveform_i(sampling_rate)

    def modulated_waveform_q(self, sampling_rate=5.89824) -> Waveform:
        """The waveform of the q component of the pulse, modulated with its
        frequency."""

        return self.shape.modulated_waveform_q(sampling_rate)

    def modulated_waveforms(self, sampling_rate):  #  -> tuple[Waveform, Waveform]:
        """A tuple with the i and q waveforms of the pulse, modulated with its
        frequency."""

        return self.shape.modulated_waveforms(sampling_rate)

    def __repr__(self):
        return self.serial

    def __hash__(self):
        return hash(self.serial)

    def __eq__(self, other):
        if isinstance(other, Pulse):
            return self.serial == other.serial
        return False

    def __add__(self, other):
        if isinstance(other, Pulse):
            return PulseSequence(self, other)
        if isinstance(other, PulseSequence):
            return PulseSequence(self, *other.pulses)
        raise TypeError(f"Expected Pulse or PulseSequence; got {type(other).__name__}")

    def __mul__(self, n):
        if not isinstance(n, int):
            raise TypeError(f"Expected int; got {type(n).__name__}")
        if n < 0:
            raise TypeError(f"argument n should be >=0, got {n}")
        return PulseSequence(*([self.copy()] * n))

    def __rmul__(self, n):
        return self.__mul__(n)

    def copy(self):  # -> Pulse|ReadoutPulse|DrivePulse|FluxPulse:
        """Returns a new Pulse object with the same attributes."""

        if type(self) == ReadoutPulse:
            return ReadoutPulse(
                self.start,
                self.duration,
                self.amplitude,
                self.frequency,
                self.relative_phase,
                repr(self.shape),  # self.shape,
                self.channel,
                self.qubit,
            )
        elif type(self) == DrivePulse:
            return DrivePulse(
                self.start,
                self.duration,
                self.amplitude,
                self.frequency,
                self.relative_phase,
                repr(self.shape),  # self.shape,
                self.channel,
                self.qubit,
            )

        elif type(self) == FluxPulse:
            return FluxPulse(
                self.start,
                self.duration,
                self.amplitude,
                self.shape,
                self.channel,
                self.qubit,
            )
        else:
            # return eval(self.serial)
            return Pulse(
                self.start,
                self.duration,
                self.amplitude,
                self.frequency,
                self.relative_phase,
                repr(self.shape),  # self.shape,
                self.channel,
                self.type,
                self.qubit,
            )

    def shallow_copy(self):  # -> Pulse:
        return Pulse(
            self.start,
            self.duration,
            self.amplitude,
            self.frequency,
            self.relative_phase,
            self.shape,
            self.channel,
            self.type,
            self.qubit,
        )

    def is_equal_ignoring_start(self, item) -> bool:
        """Check if two pulses are equal ignoring start time."""
        return (
            self.duration == item.duration
            and self.amplitude == item.amplitude
            and self.frequency == item.frequency
            and self.relative_phase == item.relative_phase
            and self.shape == item.shape
            and self.channel == item.channel
            and self.type == item.type
            and self.qubit == item.qubit
        )

    def plot(self, savefig_filename=None, sampling_rate=5.89824):
        """Plots the pulse envelope and modulated waveforms.

        Args:
            savefig_filename (str): a file path. If provided the plot is save to a file.
        """

        import matplotlib.pyplot as plt
        from matplotlib import gridspec

        waveform_i = self.shape.envelope_waveform_i(sampling_rate)
        waveform_q = self.shape.envelope_waveform_q(sampling_rate)

        num_samples = len(waveform_i)
        time = self.start + np.arange(num_samples) / sampling_rate
        fig = plt.figure(figsize=(14, 5), dpi=200)
        gs = gridspec.GridSpec(ncols=2, nrows=1, width_ratios=[2, 1])
        ax1 = plt.subplot(gs[0])
        ax1.plot(
            time,
            waveform_i.data,
            label="envelope i",
            c="C0",
            linestyle="dashed",
        )
        ax1.plot(
            time,
            waveform_q.data,
            label="envelope q",
            c="C1",
            linestyle="dashed",
        )
        ax1.plot(
            time,
            self.shape.modulated_waveform_i(sampling_rate).data,
            label="modulated i",
            c="C0",
        )
        ax1.plot(
            time,
            self.shape.modulated_waveform_q(sampling_rate).data,
            label="modulated q",
            c="C1",
        )
        ax1.plot(time, -waveform_i.data, c="silver", linestyle="dashed")
        ax1.set_xlabel("Time [ns]")
        ax1.set_ylabel("Amplitude")

        ax1.grid(
            visible=True, which="both", axis="both", color="#888888", linestyle="-"
        )
        ax1.axis([self.start, self.finish, -1, 1])
        ax1.legend()

        modulated_i = self.shape.modulated_waveform_i(sampling_rate).data
        modulated_q = self.shape.modulated_waveform_q(sampling_rate).data
        ax2 = plt.subplot(gs[1])
        ax2.plot(
            modulated_i,
            modulated_q,
            label="modulated",
            c="C3",
        )
        ax2.plot(
            waveform_i.data,
            waveform_q.data,
            label="envelope",
            c="C2",
        )
        ax2.plot(
            modulated_i[0],
            modulated_q[0],
            marker="o",
            markersize=5,
            label="start",
            c="lightcoral",
        )
        ax2.plot(
            modulated_i[-1],
            modulated_q[-1],
            marker="o",
            markersize=5,
            label="finish",
            c="darkred",
        )

        ax2.plot(
            np.cos(time * 2 * np.pi / self.duration),
            np.sin(time * 2 * np.pi / self.duration),
            c="silver",
            linestyle="dashed",
        )

        ax2.grid(
            visible=True, which="both", axis="both", color="#888888", linestyle="-"
        )
        ax2.legend()
        # ax2.axis([ -1, 1, -1, 1])
        ax2.axis("equal")
        plt.suptitle(self.serial)
        if savefig_filename:
            plt.savefig(savefig_filename)
        else:
            plt.show()
        plt.close()


class ReadoutPulse(Pulse):
    """Describes a readout pulse.

    See
    :class: `qibolab.pulses.Pulse` for argument desciption.
    """

    def __init__(
        self,
        start,
        duration,
        amplitude,
        frequency,
        relative_phase,
        shape,
        channel=0,
        qubit=0,
    ):
        super().__init__(
            start,
            duration,
            amplitude,
            frequency,
            relative_phase,
            shape,
            channel,
            type=PulseType.READOUT,
            qubit=qubit,
        )

    @property
    def serial(self):
        return f"ReadoutPulse({self.start}, {self.duration}, {format(self.amplitude, '.6f').rstrip('0').rstrip('.')}, {format(self.frequency, '_')}, {format(self.relative_phase, '.6f').rstrip('0').rstrip('.')}, {self.shape}, {self.channel}, {self.qubit})"

    @property
    def global_phase(self):
        # readout pulses should have zero global phase so that we can
        # calculate probabilities in the i-q plane
        return 0

    def copy(self):  # -> Pulse|ReadoutPulse|DrivePulse|FluxPulse:
        """Returns a new Pulse object with the same attributes."""

        return ReadoutPulse(
            self.start,
            self.duration,
            self.amplitude,
            self.frequency,
            self.relative_phase,
            copy.deepcopy(self.shape),  # self.shape,
            self.channel,
            self.qubit,
        )


class DrivePulse(Pulse):
    """Describes a qubit drive pulse.

    See
    :class: `qibolab.pulses.Pulse` for argument desciption.
    """

    def __init__(
        self,
        start,
        duration,
        amplitude,
        frequency,
        relative_phase,
        shape,
        channel=0,
        qubit=0,
    ):
        super().__init__(
            start,
            duration,
            amplitude,
            frequency,
            relative_phase,
            shape,
            channel,
            type=PulseType.DRIVE,
            qubit=qubit,
        )

    @property
    def serial(self):
        return f"DrivePulse({self.start}, {self.duration}, {format(self.amplitude, '.6f').rstrip('0').rstrip('.')}, {format(self.frequency, '_')}, {format(self.relative_phase, '.6f').rstrip('0').rstrip('.')}, {self.shape}, {self.channel}, {self.qubit})"


class FluxPulse(Pulse):
    """Describes a qubit flux pulse.

    Flux pulses have frequency and relative_phase equal to 0. Their i
    and q components are equal. See
    :class: `qibolab.pulses.Pulse` for argument desciption.
    """

    PULSE_TYPE = PulseType.FLUX

    def __init__(self, start, duration, amplitude, shape, channel=0, qubit=0):
        super().__init__(
            start,
            duration,
            amplitude,
            0,
            0,
            shape,
            channel,
            type=self.PULSE_TYPE,
            qubit=qubit,
        )

    def envelope_waveform_q(self, sampling_rate=5.89824) -> Waveform:
        """Flux pulses only have i component."""
        return self.shape.envelope_waveform_i(sampling_rate)

    def modulated_waveform_i(self, sampling_rate=5.89824) -> Waveform:
        return self.shape.envelope_waveform_i(sampling_rate)

    def modulated_waveform_q(self, sampling_rate=5.89824) -> Waveform:
        return self.shape.envelope_waveform_i(sampling_rate)

    @property
    def serial(self):
        return f"{self.__class__.__name__}({self.start}, {self.duration}, {format(self.amplitude, '.6f').rstrip('0').rstrip('.')}, {self.shape}, {self.channel}, {self.qubit})"


class CouplerFluxPulse(FluxPulse):
    """Describes a coupler flux pulse.

    See
    :class: `qibolab.pulses.FluxPulse` for argument desciption.
    """

    PULSE_TYPE = PulseType.COUPLERFLUX


class PulseConstructor(Enum):
    """An enumeration to map each ``PulseType`` to the proper pulse
    constructor."""

    READOUT = ReadoutPulse
    DRIVE = DrivePulse
    FLUX = FluxPulse


class PulseSequence:
    """A collection of scheduled pulses.

    A quantum circuit can be translated into a set of scheduled pulses
    that implement the circuit gates. This class contains many
    supporting fuctions to facilitate the creation and manipulation of
    these collections of pulses. None of the methods of PulseSequence
    modify any of the properties of its pulses.
    """

    def __init__(self, *pulses):
        self.pulses = []  #: list[Pulse] = []
        """Pulses (list): a list containing the pulses, ordered by their
        channel and start times."""
        self.add(*pulses)

    def __len__(self):
        return len(self.pulses)

    def __iter__(self):
        return iter(self.pulses)

    def __getitem__(self, index):
        return self.pulses[index]

    def __setitem__(self, index, value):
        self.pulses[index] = value

    def __delitem__(self, index):
        del self.pulses[index]

    def __contains__(self, pulse):
        return pulse in self.pulses

    def __repr__(self):
        return self.serial

    @property
    def serial(self):
        """Returns a string representation of the pulse sequence."""

        return "PulseSequence\n" + "\n".join(f"{pulse.serial}" for pulse in self.pulses)

    def __eq__(self, other):
        if not isinstance(other, PulseSequence):
            raise TypeError(f"Expected PulseSequence; got {type(other).__name__}")
        return self.serial == other.serial

    def __ne__(self, other):
        if not isinstance(other, PulseSequence):
            raise TypeError(f"Expected PulseSequence; got {type(other).__name__}")
        return self.serial != other.serial

    def __hash__(self):
        return hash(self.serial)

    def __add__(self, other):
        if isinstance(other, PulseSequence):
            return PulseSequence(*self.pulses, *other.pulses)
        if isinstance(other, Pulse):
            return PulseSequence(*self.pulses, other)
        raise TypeError(f"Expected PulseSequence or Pulse; got {type(other).__name__}")

    def __radd__(self, other):
        if isinstance(other, PulseSequence):
            return PulseSequence(*other.pulses, *self.pulses)
        if isinstance(other, Pulse):
            return PulseSequence(other, *self.pulses)
        raise TypeError(f"Expected PulseSequence or Pulse; got {type(other).__name__}")

    def __iadd__(self, other):
        if isinstance(other, PulseSequence):
            self.add(*other.pulses)
        elif isinstance(other, Pulse):
            self.add(other)
        else:
            raise TypeError(
                f"Expected PulseSequence or Pulse; got {type(other).__name__}"
            )
        return self

    def __mul__(self, n):
        if not isinstance(n, int):
            raise TypeError(f"Expected int; got {type(n).__name__}")
        if n < 0:
            raise TypeError(f"argument n should be >=0, got {n}")
        return PulseSequence(*(self.pulses * n))

    def __rmul__(self, n):
        if not isinstance(n, int):
            raise TypeError(f"Expected int; got {type(n).__name__}")
        if n < 0:
            raise TypeError(f"argument n should be >=0, got {n}")
        return PulseSequence(*(self.pulses * n))

    def __imul__(self, n):
        if not isinstance(n, int):
            raise TypeError(f"Expected int; got {type(n).__name__}")
        if n < 1:
            raise TypeError(f"argument n should be >=1, got {n}")
        original_set = self.shallow_copy()
        for x in range(n - 1):
            self.add(*original_set.pulses)
        return self

    @property
    def count(self):
        """Returns the number of pulses in the sequence."""

        return len(self.pulses)

    def add(self, *items):
        """Adds pulses to the sequence and sorts them by channel and start
        time."""

        for item in items:
            if isinstance(item, Pulse):
                pulse = item
                self.pulses.append(pulse)
            elif isinstance(item, PulseSequence):
                ps = item
                for pulse in ps.pulses:
                    self.pulses.append(pulse)
        self.pulses.sort(key=lambda item: (item.start, item.channel))

    def index(self, pulse):
        """Returns the index of a pulse in the sequence."""

        return self.pulses.index(pulse)

    def pop(self, index=-1):
        """Returns the pulse with the index provided and removes it from the
        sequence."""

        return self.pulses.pop(index)

    def remove(self, pulse):
        """Removes a pulse from the sequence."""

        while pulse in self.pulses:
            self.pulses.remove(pulse)

    def clear(self):
        """Removes all pulses from the sequence."""

        self.pulses.clear()

    def shallow_copy(self):
        """Returns a shallow copy of the sequence.

        It returns a new PulseSequence object with references to the
        same Pulse objects.
        """

        return PulseSequence(*self.pulses)

    def copy(self):
        """Returns a deep copy of the sequence.

        It returns a new PulseSequence with replicates of each of the
        pulses contained in the original sequence.
        """

        return PulseSequence(*[pulse.copy() for pulse in self.pulses])

    @property
    def ro_pulses(self):
        """Returns a new PulseSequence containing only its readout pulses."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if pulse.type == PulseType.READOUT:
                new_pc.add(pulse)
        return new_pc

    @property
    def qd_pulses(self):
        """Returns a new PulseSequence containing only its qubit drive
        pulses."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if pulse.type == PulseType.DRIVE:
                new_pc.add(pulse)
        return new_pc

    @property
    def qf_pulses(self):
        """Returns a new PulseSequence containing only its qubit flux
        pulses."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if pulse.type == PulseType.FLUX:
                new_pc.add(pulse)
        return new_pc

    @property
    def cf_pulses(self):
        """Returns a new PulseSequence containing only its coupler flux
        pulses."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if pulse.type is PulseType.COUPLERFLUX:
                new_pc.add(pulse)
        return new_pc

    def get_channel_pulses(self, *channels):
        """Returns a new PulseSequence containing only the pulses on a specific
        set of channels."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if pulse.channel in channels:
                new_pc.add(pulse)
        return new_pc

    def get_qubit_pulses(self, *qubits):
        """Returns a new PulseSequence containing only the pulses on a specific
        set of qubits."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if not isinstance(pulse, CouplerFluxPulse):
                if pulse.qubit in qubits:
                    new_pc.add(pulse)
        return new_pc

    def coupler_pulses(self, *couplers):
        """Returns a new PulseSequence containing only the pulses on a specific
        set of couplers."""

        new_pc = PulseSequence()
        for pulse in self.pulses:
            if isinstance(pulse, CouplerFluxPulse):
                if pulse.qubit in couplers:
                    new_pc.add(pulse)
        return new_pc

    @property
    def is_empty(self):
        """Returns True if the sequence does not contain any pulses."""

        return len(self.pulses) == 0

    @property
    def finish(self) -> int:
        """Returns the time when the last pulse of the sequence finishes."""

        t: int = 0
        for pulse in self.pulses:
            if pulse.finish > t:
                t = pulse.finish
        return t

    @property
    def start(self) -> int:
        """Returns the start time of the first pulse of the sequence."""

        t = self.finish
        for pulse in self.pulses:
            if pulse.start < t:
                t = pulse.start
        return t

    @property
    def duration(self) -> int:
        """Returns duration of the sequence calculated as its finish - start times."""

        return self.finish - self.start

    @property
    def channels(self) -> list:
        """Returns list containing the channels used by the pulses in the
        sequence."""

        channels = []
        for pulse in self.pulses:
            if not pulse.channel in channels:
                channels.append(pulse.channel)
        channels.sort()
        return channels

    @property
    def qubits(self) -> list:
        """Returns list containing the qubits associated with the pulses in the
        sequence."""

        qubits = []
        for pulse in self.pulses:
            if not pulse.qubit in qubits:
                qubits.append(pulse.qubit)
        qubits.sort()
        return qubits

    def get_pulse_overlaps(self):  # -> dict((int,int): PulseSequence):
        """Returns a dictionary of slices of time (tuples with start and finish
        times) where pulses overlap."""

        times = []
        for pulse in self.pulses:
            if not pulse.start in times:
                times.append(pulse.start)
            if not pulse.finish in times:
                times.append(pulse.finish)
        times.sort()

        overlaps = {}
        for n in range(len(times) - 1):
            overlaps[(times[n], times[n + 1])] = PulseSequence()
            for pulse in self.pulses:
                if (pulse.start <= times[n]) & (pulse.finish >= times[n + 1]):
                    overlaps[(times[n], times[n + 1])] += pulse
        return overlaps

    def separate_overlapping_pulses(self):  # -> dict((int,int): PulseSequence):
        """Separates a sequence of overlapping pulses into a list of non-
        overlapping sequences."""

        # This routine separates the pulses of a sequence into non-overlapping sets
        # but it does not check if the frequencies of the pulses within a set have the same frequency

        separated_pulses = []
        for new_pulse in self.pulses:
            stored = False
            for ps in separated_pulses:
                overlaps = False
                for existing_pulse in ps:
                    if (
                        new_pulse.start < existing_pulse.finish
                        and new_pulse.finish > existing_pulse.start
                    ):
                        overlaps = True
                        break
                if not overlaps:
                    ps.add(new_pulse)
                    stored = True
                    break
            if not stored:
                separated_pulses.append(PulseSequence(new_pulse))
        return separated_pulses

    # TODO: Implement separate_different_frequency_pulses()

    @property
    def pulses_overlap(self) -> bool:
        """Returns True if any of the pulses in the sequence overlap."""

        overlap = False
        for pc in self.get_pulse_overlaps().values():
            if pc.count > 1:
                overlap = True
        return overlap

    def plot(self, savefig_filename=None, sampling_rate=5.89824):
        """Plots the sequence of pulses.

        Args:
            savefig_filename (str): a file path. If provided the plot is save to a file.
        """

        if not self.is_empty:
            import matplotlib.pyplot as plt
            from matplotlib import gridspec

            fig = plt.figure(figsize=(14, 2 * self.count), dpi=200)
            gs = gridspec.GridSpec(ncols=1, nrows=self.count)
            vertical_lines = []
            for pulse in self.pulses:
                vertical_lines.append(pulse.start)
                vertical_lines.append(pulse.finish)

            n = -1
            for qubit in self.qubits:
                qubit_pulses = self.get_qubit_pulses(qubit)
                for channel in qubit_pulses.channels:
                    n += 1
                    channel_pulses = qubit_pulses.get_channel_pulses(channel)
                    ax = plt.subplot(gs[n])
                    ax.axis([0, self.finish, -1, 1])
                    for pulse in channel_pulses:
                        num_samples = len(
                            pulse.shape.modulated_waveform_i(sampling_rate)
                        )
                        time = pulse.start + np.arange(num_samples) / sampling_rate
                        ax.plot(
                            time,
                            pulse.shape.modulated_waveform_q(sampling_rate).data,
                            c="lightgrey",
                        )
                        ax.plot(
                            time,
                            pulse.shape.modulated_waveform_i(sampling_rate).data,
                            c=f"C{str(n)}",
                        )
                        ax.plot(
                            time,
                            pulse.shape.envelope_waveform_i(sampling_rate).data,
                            c=f"C{str(n)}",
                        )
                        ax.plot(
                            time,
                            -pulse.shape.envelope_waveform_i(sampling_rate).data,
                            c=f"C{str(n)}",
                        )
                        # TODO: if they overlap use different shades
                        ax.axhline(0, c="dimgrey")
                        ax.set_ylabel(f"qubit {qubit} \n channel {channel}")
                        for vl in vertical_lines:
                            ax.axvline(vl, c="slategrey", linestyle="--")
                        ax.axis([0, self.finish, -1, 1])
                        ax.grid(
                            visible=True,
                            which="both",
                            axis="both",
                            color="#CCCCCC",
                            linestyle="-",
                        )
            if savefig_filename:
                plt.savefig(savefig_filename)
            else:
                plt.show()
            plt.close()