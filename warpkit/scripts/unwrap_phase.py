"""A workflow to unwrap multi-echo phase data."""

import argparse
import json
import logging
from functools import partial
from pathlib import Path

import nibabel as nib

from warpkit.distortion import medic
from warpkit.scripts import epilog
from warpkit.utilities import setup_logging


def main():
    """Build parser object and run workflow."""

    def _path_exists(path, parser):
        """Ensure a given path exists."""
        if path is None or not Path(path).exists():
            raise parser.error(f"Path does not exist: <{path}>.")
        return Path(path).absolute()

    def _is_file(path, parser):
        """Ensure a given path exists and it is a file."""
        path = _path_exists(path, parser)
        if not path.is_file():
            raise parser.error(f"Path should point to a file (or symlink of file): <{path}>.")
        return path

    parser = argparse.ArgumentParser(
        description="Unwrap multi-echo phase data",
        epilog=f"{epilog} 12/09/2022",
    )

    IsFile = partial(_is_file, parser=parser)

    parser.add_argument(
        "--magnitude",
        nargs="+",
        required=True,
        metavar="FILE",
        type=IsFile,
        help="Magnitude data",
    )
    parser.add_argument(
        "--phase",
        nargs="+",
        required=True,
        metavar="FILE",
        type=IsFile,
        help="Phase data",
    )
    parser.add_argument(
        "--metadata",
        nargs="+",
        required=True,
        metavar="FILE",
        type=IsFile,
        help=(
            "JSON sidecar for each echo. "
            "Three fields are required: EchoTime, TotalReadoutTime, and PhaseEncodingDirection."
        ),
    )
    parser.add_argument(
        "--out_prefix",
        help="Prefix to output field maps and displacment maps.",
    )
    parser.add_argument(
        "-f",
        "--noiseframes",
        type=int,
        default=0,
        help=(
            "Number of noise frames at the end of the run. "
            "Noise frames will be removed before unwrapping is performed."
        ),
    )
    parser.add_argument(
        "-n",
        "--n_cpus",
        type=int,
        default=4,
        help="Number of CPUs to use.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug mode",
    )
    parser.add_argument(
        "--wrap_limit",
        action="store_true",
        default=False,
        help="Turns off some heuristics for phase unwrapping",
    )

    # parse arguments
    args = parser.parse_args()

    # setup logging
    setup_logging()

    # log arguments
    logging.info(f"unwrap_phases: {args}")
    kwargs = vars(args)
    unwrap_phases(**kwargs)


def unwrap_phases(
    *,
    magnitude,
    phase,
    metadata,
    out_prefix,
    noiseframes,
    n_cpus,
    debug,
    wrap_limit,
):

    # load magnitude and phase data
    mag_data = [nib.load(m) for m in magnitude]
    phase_data = [nib.load(p) for p in phase]

    # if noiseframes specified, remove them
    if noiseframes > 0:
        logging.info(f"Removing {noiseframes} noise frames from the end of the run...")
        mag_data = [m.slicer[..., : -noiseframes] for m in mag_data]
        phase_data = [p.slicer[..., : -noiseframes] for p in phase_data]

    # check if data is 4D or 3D
    if len(phase[0].shape) == 3:
        # set total number of frames to 1
        n_frames = 1
        # convert data to 4D
        phase = [nib.Nifti1Image(p.get_fdata()[..., np.newaxis], p.affine, p.header) for p in phase]
        mag = [nib.Nifti1Image(m.get_fdata()[..., np.newaxis], m.affine, m.header) for m in mag]
    elif len(phase[0].shape) == 4:
        # if frames is None, set it to all frames
        if frames is None:
            frames = list(range(phase[0].shape[-1]))
        # get the total number of frames
        n_frames = len(frames)
    else:
        raise ValueError("Data must be 3D or 4D.")

    # get metadata
    echo_times = []
    total_readout_time = None
    phase_encoding_direction = None
    for i_run, json_file in enumerate(metadata):
        with open(json_file, "r") as fobj:
            metadata_dict = json.load(fobj)
            echo_times.append(metadata_dict["EchoTime"] * 1000)  # convert TE from s to ms

        if i_run == 0:
            total_readout_time = metadata_dict.get("TotalReadoutTime")
            phase_encoding_direction = metadata_dict.get("PhaseEncodingDirection")

    if total_readout_time is None:
        raise ValueError("Could not find 'TotalReadoutTime' field in metadata.")

    if phase_encoding_direction is None:
        raise ValueError("Could not find 'PhaseEncodingDirection' field in metadata.")

    # Sort the echo times and data by echo time
    echo_times, mag_data, phase_data = zip(*sorted(zip(echo_times, mag_data, phase_data)))

    # now run MEDIC's phase-unwrapping method
    unwrap_phase_data(
        phase=phase_data,
        mag=mag_data,
        TEs=echo_times,
        total_readout_time,
        phase_encoding_direction,
        out_prefix,
        n_cpus,
        debug,
        wrap_limit,
    )
    if debug:
        fmaps_native, dmaps, fmaps = medic(
            phase_data,
            mag_data,
            echo_times,
            total_readout_time,
            phase_encoding_direction,
            n_cpus=n_cpus,
            border_filt=(1000, 1000),
            svd_filt=1000,
            debug=True,
            wrap_limit=wrap_limit,
        )
    else:
        fmaps_native, dmaps, fmaps = medic(
            phase_data,
            mag_data,
            echo_times,
            total_readout_time,
            phase_encoding_direction,
            n_cpus=n_cpus,
            svd_filt=10,
            border_size=5,
            wrap_limit=wrap_limit,
        )

    # save the fmaps and dmaps to file
    logging.info("Saving field maps and displacement maps to file...")
    fmaps_native.to_filename(f"{out_prefix}_fieldmaps_native.nii")
    dmaps.to_filename(f"{out_prefix}_displacementmaps.nii")
    fmaps.to_filename(f"{out_prefix}_fieldmaps.nii")
    logging.info("Done.")
