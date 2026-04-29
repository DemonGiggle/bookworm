from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

from ..core.models import DocumentSection, EmbeddedImage, ImageAnalysis
from ..images.base import ImageAnalyzer

_MIME_TYPES_BY_SUFFIX = {
    ".emf": "image/x-emf",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".wmf": "image/x-wmf",
}
_VECTOR_IMAGE_SUFFIXES = {".emf", ".wmf"}
_VECTOR_IMAGE_MIME_TYPES = {"image/emf", "image/x-emf", "image/wmf", "image/x-wmf"}


def mime_type_for_filename(filename: str) -> str:
    return _MIME_TYPES_BY_SUFFIX.get(PurePosixPath(filename).suffix.lower(), "application/octet-stream")


def render_image_analysis(image: EmbeddedImage, analysis: ImageAnalysis) -> str:
    lines = [
        "This section summarizes an embedded image from the source document.",
        "",
        "Visual summary: {summary}".format(summary=analysis.summary.strip()),
    ]
    if image.filename.strip():
        lines.extend(
            [
                "",
                "Image file: {filename}".format(filename=image.filename.strip()),
            ]
        )
    if image.caption.strip():
        lines.extend(
            [
                "",
                "Inline caption or nearby text: {caption}".format(caption=image.caption.strip()),
            ]
        )
    if image.context_text.strip():
        lines.extend(
            [
                "",
                "Nearby document context:",
                image.context_text.strip(),
            ]
        )
    if analysis.key_points:
        lines.extend(["", "Key visual details:"])
        lines.extend("- {point}".format(point=point) for point in analysis.key_points)
    return "\n".join(lines)


def image_metadata_line(image: EmbeddedImage) -> str:
    return (
        "{locator}: file={filename}, mime={mime_type}, bytes={byte_count}"
    ).format(
        locator=image.source_ref.locator,
        filename=image.filename or "(unnamed)",
        mime_type=image.mime_type or "application/octet-stream",
        byte_count=len(image.data),
    )


def _image_requires_png_normalization(image: EmbeddedImage) -> bool:
    suffix = PurePosixPath(image.filename).suffix.lower()
    return suffix in _VECTOR_IMAGE_SUFFIXES or image.mime_type.lower() in _VECTOR_IMAGE_MIME_TYPES


def _image_converter_command(input_path: Path, output_path: Path) -> Optional[List[str]]:
    inkscape = shutil.which("inkscape")
    if inkscape:
        try:
            help_result = subprocess.run(
                [inkscape, "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            help_text = "{stdout}\n{stderr}".format(
                stdout=help_result.stdout,
                stderr=help_result.stderr,
            )
        except Exception:
            help_text = ""
        if "--export-png" in help_text:
            return [inkscape, "--without-gui", str(input_path), "--export-png={output_path}".format(
                output_path=output_path,
            )]
        return [
            inkscape,
            str(input_path),
            "--export-type=png",
            "--export-filename={output_path}".format(output_path=output_path),
        ]
    magick = shutil.which("magick")
    if magick:
        return [magick, str(input_path), str(output_path)]
    convert = shutil.which("convert")
    if convert:
        return [convert, str(input_path), str(output_path)]
    return None


def normalize_image_for_analysis(image: EmbeddedImage) -> Tuple[Optional[EmbeddedImage], str]:
    if not _image_requires_png_normalization(image):
        return image, ""
    suffix = PurePosixPath(image.filename).suffix.lower() or ".img"
    try:
        with tempfile.TemporaryDirectory(prefix="bookworm-image-") as directory:
            input_path = Path(directory) / "input{suffix}".format(suffix=suffix)
            output_path = Path(directory) / "output.png"
            input_path.write_bytes(image.data)
            command = _image_converter_command(input_path=input_path, output_path=output_path)
            if command is None:
                return (
                    None,
                    (
                        "Image {details} uses a vector preview format that most vision APIs cannot decode, "
                        "and no Inkscape or ImageMagick converter was found."
                    ).format(details=image_metadata_line(image)),
                )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "converter exited with a non-zero status").strip()
                return (
                    None,
                    "Unable to convert {details} to PNG: {detail}".format(
                        details=image_metadata_line(image),
                        detail=detail,
                    ),
                )
            converted_data = output_path.read_bytes()
    except Exception as error:
        return (
            None,
            "Unable to convert {details} to PNG: {error}".format(
                details=image_metadata_line(image),
                error=error,
            ),
        )
    converted_filename = "{stem}.png".format(stem=PurePosixPath(image.filename).stem or "image")
    converted_image = replace(
        image,
        filename=converted_filename,
        mime_type="image/png",
        data=converted_data,
    )
    return converted_image, "Normalized embedded image for analysis: {original} -> {converted}.".format(
        original=image_metadata_line(image),
        converted=image_metadata_line(converted_image),
    )


def analyze_embedded_images(
    sections: List[DocumentSection],
    embedded_images: List[EmbeddedImage],
    image_analyzer: Optional[ImageAnalyzer],
) -> Tuple[List[str], List[str]]:
    notes: List[str] = []
    warnings: List[str] = []
    if embedded_images:
        notes.append(
            "Detected {count} embedded image(s): {details}.".format(
                count=len(embedded_images),
                details="; ".join(image_metadata_line(image) for image in embedded_images),
            )
        )
    if embedded_images and image_analyzer is None:
        warnings.append(
            "Detected {count} embedded image(s) but no image analyzer is configured; image content was skipped."
            .format(count=len(embedded_images))
        )
    if image_analyzer is not None:
        for index, image in enumerate(embedded_images, start=1):
            analysis_image, normalization_message = normalize_image_for_analysis(image)
            if normalization_message and analysis_image is not None:
                notes.append(normalization_message)
            if normalization_message and analysis_image is None:
                warnings.append(
                    "Skipped embedded image {index}: {message}".format(
                        index=index,
                        message=normalization_message,
                    )
                )
                continue
            notes.append(
                "Analyzing embedded image {index}: {details}.".format(
                    index=index,
                    details=image_metadata_line(analysis_image),
                )
            )
            try:
                analysis = image_analyzer.analyze(analysis_image)
                sections.append(
                    DocumentSection(
                        heading="Embedded image {index}".format(index=index),
                        content=render_image_analysis(analysis_image, analysis),
                        source_ref=analysis_image.source_ref,
                        content_kind="image-analysis",
                    )
                )
                notes.append("Analyzed embedded image {index} successfully.".format(index=index))
            except Exception as error:
                warnings.append(
                    "Failed to analyze embedded image {index}: {error}".format(
                        index=index,
                        error=error,
                    )
                )
    return notes, warnings
