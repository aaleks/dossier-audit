"""An image in, one page image out (spec 008).

R8.10 resolved `image/png` to `page_images` and nothing produced that pair, so
its row 4 fired for every image: the default decided which pair a person had to
claim, and no converter claimed it. A screenshot could be synced, held and
hashed, and never converted.

An image is one page. There is nothing to render and no text to extract, so the
only real decision here is that the conversion is still a *container* (R8.11)
rather than the bare bytes: a step reading `page_images` then sees one interface
whatever produced it, and a picture and a forty-page PDF fan out through the
same `per_part` code (R3.12).

Two converters rather than one with two media types, for the reason `text-plain`
is separate from `markdown-text`: a converter claims exactly one pair (R8.3), and
registration is what makes that claim. They share their body, not their identity,
and their versions move independently (R5.4).

**No model is reached here**, as in every converter: this sits right of the hash
boundary (R0.19) and is a pure function of bytes and options (R8.1).
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.domain.conversion import pack_parts
from dossier.infrastructure.converters._png import png

# Every part of a `page_images` artifact is a PNG. The parts carry no media type
# of their own -- the composition root labels each one `image/png` as it unpacks
# a container -- so a JPEG passed through verbatim would be handed to a provider
# under a type it is not. `pdf-images` already produces PNG, so this is the
# kind's existing promise rather than a new one.
PART_SUFFIX = ".png"


class _ImagePagesConverter:
    """The shared body: one image becomes a container holding one page."""

    id = "image-pages"
    version = "1.0.0"
    media_type = "image/png"
    kind = "page_images"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The image as a one-part container.

        `options` is accepted and unused: this converter has none. There is
        deliberately no scale option -- unlike `pdf-images`, which must choose a
        rendering resolution, an image already *is* its resolution, and
        resampling it would be this converter inventing detail or discarding it.
        """
        return pack_parts([self._png(payload)], suffix=PART_SUFFIX)

    def _png(self, payload: bytes) -> bytes:
        """This image's bytes as a PNG."""
        raise NotImplementedError


class PngPagesConverter(_ImagePagesConverter):
    """`image/png` to the `page_images` kind, copied rather than re-encoded."""

    id = "png-pages"
    version = "1.0.0"
    media_type = "image/png"

    def _png(self, payload: bytes) -> bytes:
        """The source bytes, untouched.

        A PNG is already what a part must be, so decoding and re-encoding it
        would spend Pillow's opinion about compression on a file that needs
        none -- and would make the artifact depend on a library version that
        the converter's own `version` does not name (R8.1 row 2, R5.4).
        """
        return payload


class JpegPagesConverter(_ImagePagesConverter):
    """`image/jpeg` to the `page_images` kind, re-encoded as PNG."""

    id = "jpeg-pages"
    # Raise this whenever output could change for the same input. That covers
    # the pinned Pillow underneath -- its decoder decides the pixels -- and the
    # pinned `deflate` that compresses them (R8.29). Neither can be discovered
    # from the artifact afterwards. 1.1.0: written by `_png`, not Pillow's
    # encoder, whose bytes differed between Windows and Linux.
    version = "1.1.0"
    media_type = "image/jpeg"

    def _png(self, payload: bytes) -> bytes:
        """The decoded pixels, written as PNG.

        Lossless of what the JPEG holds: the decode is the lossy step and it
        already happened when the file was written. Imported here rather than at
        module scope so the entry point loads on an installation without the
        `pdf` extra, the same reasoning as `pdf-markdown`.
        """
        try:
            import io

            from PIL import Image
        except ImportError as error:  # pragma: no cover - depends on the install
            raise ValueError(
                f"{self.id} needs the 'pdf' extra: install dossier[pdf]"
            ) from error

        try:
            image = Image.open(io.BytesIO(payload))
            image.load()
        except Exception as error:
            # R8.6's shape: one document fails with a reason and the others
            # convert. A truncated JPEG is a bad input, not a misconfigured
            # pipeline (R8.24).
            raise ValueError(f"{self.id} could not read this image: {error}") from error

        # Not Pillow's encoder: its bytes depend on the zlib its wheel was built
        # with, and Windows and Linux wheels differ (R8.29).
        return png(image)
