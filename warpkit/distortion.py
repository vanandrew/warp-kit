from typing import List, Tuple, Union
import nibabel as nib
import numpy as np
from warpkit.unwrap import unwrap_and_compute_field_maps
from warpkit.utilities import field_maps_to_displacement_maps, invert_displacement_maps


def me_sdc(
    phase: List[nib.Nifti1Image],
    mag: List[nib.Nifti1Image],
    TEs: Union[List[float], Tuple[float]],
    effective_echo_spacing: float,
    phase_encoding_direction: str,
    up_to_frame: Union[int, None] = None,
) -> nib.Nifti1Image:
    """Unwrap phase of data weighted by magnitude data and compute displacment maps
    for correction.

    Parameters
    ----------
    phase : List[nib.Nifti1Image]
        Phases to unwrap
    mag : List[nib.Nifti1Image]
        Magnitudes associated with each phase
    TEs : Union[List[float], Tuple[float]]
        Echo times associated with each phase
    effective_echo_spacing : float
        Effective echo spacing
    phase_encoding_direction : str
        Phase encoding direction (can be i, j, k, i-, j-, k-) or (x, y, z, x-, y-, z-)
    up_to_frame : int, optional
        Only use up to this frame, by default None

    Returns
    -------
    nib.Nifti1Image
        Field maps in Hz
    nib.Nifti1Image
        Correction maps (distorted -> undistorted) in mm
    """
    # make sure affines/shapes are all correct
    for p1, m1 in zip(phase, mag):
        for p2, m2 in zip(phase, mag):
            if not (
                np.allclose(p1.affine, p2.affine)
                and np.allclose(m1.affine, m2.affine)
                and p1.shape == p2.shape
                and m1.shape == m2.shape
            ):
                raise ValueError("Affines and shapes must match")

    # unwrap phase and compute field maps
    field_maps = unwrap_and_compute_field_maps(phase, mag, TEs, up_to_frame=up_to_frame)

    # convert to displacement maps
    displacement_maps = field_maps_to_displacement_maps(field_maps, effective_echo_spacing, phase_encoding_direction)

    # invert displacement maps
    correction_maps = invert_displacement_maps(displacement_maps, phase_encoding_direction, True)

    # return correction maps
    return field_maps, correction_maps
