"""Scan preprocessing to lift OCR quality on real-world Bangladeshi scans.

`enhance()` runs a conservative, color-preserving pipeline before OCR:
  * shadow / uneven-background removal (background division)
  * contrast (CLAHE on the luminance channel)
  * light denoise (kept mild so thin Bangla matras/conjuncts survive)
  * deskew (small-angle rotation, clamped — never flips or hard-rotates)

It is deliberately defensive: any failure returns the original image unchanged,
so preprocessing can never break a conversion. Operations run on the L channel of
LAB space and are recombined, so extracted figures keep their colour.
"""

import cv2
import numpy as np
from PIL import Image

# Deskew is only trusted for small angles; a large estimate is almost always a
# figure-heavy / sparse page fooling minAreaRect, so we skip it rather than rotate.
_MAX_SKEW_DEG = 15.0
_MIN_SKEW_DEG = 0.1  # below this, rotation isn't worth the interpolation blur

# fastNlMeansDenoising is O(area); on very large renders it is too slow to be
# worth it (the scan is already high-res), so skip denoise past this longest side.
_MAX_DENOISE_DIM = 4000


def enhance(
    img: Image.Image,
    *,
    deskew: bool = True,
    denoise: bool = True,
    contrast: bool = True,
    shadow: bool = True,
) -> Image.Image:
    """Return a cleaned-up copy of `img` for OCR. On any error, returns `img`."""
    try:
        rgb = np.asarray(img.convert("RGB"))
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)

        # Estimate skew up front on the raw luminance: the tonal steps below
        # (esp. contrast) amplify background noise and flatten the projection
        # profile, so measuring afterwards gives a useless angle.
        angle = _estimate_skew(l) if deskew else 0.0

        # Order matters: denoise FIRST. Otherwise contrast (CLAHE) turns faint
        # background noise into speckle that destroys OCR — denoising first keeps
        # the page clean enough for the later steps to only help.
        if denoise and max(l.shape) <= _MAX_DENOISE_DIM:
            l = cv2.fastNlMeansDenoising(l, h=10, templateWindowSize=7, searchWindowSize=21)
        if shadow:
            l = _remove_shadow(l)
        if contrast:
            # Gentle clip: enough to lift faded scans, low enough not to re-amplify
            # residual noise into the background.
            l = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(l)

        out = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2RGB)

        if deskew and _MIN_SKEW_DEG < abs(angle) <= _MAX_SKEW_DEG:
            out = _rotate(out, angle)

        return Image.fromarray(out)
    except Exception:
        return img


def _remove_shadow(chan: np.ndarray) -> np.ndarray:
    """Flatten uneven background / scanner shadows via background division."""
    dilated = cv2.dilate(chan, np.ones((7, 7), np.uint8))
    bg = cv2.medianBlur(dilated, 21)
    diff = 255 - cv2.absdiff(chan, bg)
    return cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


# How finely the deskew search scans candidate angles, and the size it downscales
# the binarised page to first (the profile is shape-driven, so low-res is plenty
# and keeps the ~60-rotation search fast on full-resolution scans).
_SKEW_STEP_DEG = 0.5
_SKEW_SEARCH_DIM = 1000


def _estimate_skew(l: np.ndarray) -> float:
    """Estimate the correction angle (deg) via a horizontal projection profile.

    Returns the angle to rotate by so text lines become horizontal. A
    projection-profile search avoids the width/height ambiguity that makes
    minAreaRect flip wide text blocks to ~90 degrees.
    """
    thr = cv2.threshold(l, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    if int((thr > 0).sum()) < 50:  # too few ink pixels to trust an angle
        return 0.0

    longest = max(thr.shape)
    if longest > _SKEW_SEARCH_DIM:
        scale = _SKEW_SEARCH_DIM / longest
        thr = cv2.resize(thr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    best_angle, best_score = 0.0, -1.0
    angle = -_MAX_SKEW_DEG
    while angle <= _MAX_SKEW_DEG:
        rotated = _rotate_gray(thr, angle)
        profile = rotated.sum(axis=1, dtype=np.float64)
        # When lines are horizontal, row sums concentrate into sharp peaks, so the
        # sum of squared row sums is maximal at the correct angle.
        score = float(np.sum(profile * profile))
        if score > best_score:
            best_score, best_angle = score, angle
        angle += _SKEW_STEP_DEG
    return best_angle


def _rotate_gray(img: np.ndarray, angle: float) -> np.ndarray:
    """Rotate a single-channel binary image; new corners are background (0)."""
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    """Rotate by `angle` degrees about the centre, filling new corners with white."""
    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
