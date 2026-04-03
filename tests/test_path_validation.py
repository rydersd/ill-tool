"""Tests for path_validation module.

Tests path traversal prevention, symlink resolution, allowed_prefixes
enforcement, and image dimension validation (both in-memory and
header-only pre-decode).
"""

import os
import struct
import tempfile

import numpy as np
import pytest

from adobe_mcp.apps.illustrator.path_validation import (
    MAX_IMAGE_DIM,
    validate_image_path_size,
    validate_image_size,
    validate_safe_path,
)


# ---------------------------------------------------------------------------
# validate_safe_path — traversal rejection
# ---------------------------------------------------------------------------


class TestValidateSafePath:
    """Tests for validate_safe_path path traversal prevention."""

    def test_rejects_path_with_dotdot(self, tmp_path):
        """Paths containing '..' components are rejected."""
        evil_path = str(tmp_path / "foo" / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="traversal"):
            validate_safe_path(evil_path)

    def test_rejects_leading_dotdot(self):
        """Leading '..' is rejected."""
        with pytest.raises(ValueError, match="traversal"):
            validate_safe_path("../../etc/passwd")

    def test_rejects_empty_path(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            validate_safe_path("")

    def test_accepts_valid_absolute_path(self, tmp_path):
        """A valid absolute path is returned resolved."""
        test_file = tmp_path / "valid.txt"
        test_file.write_text("ok")

        result = validate_safe_path(str(test_file))
        assert result == str(test_file.resolve())

    def test_accepts_valid_path_without_file_existing(self, tmp_path):
        """A valid path that does not yet exist is still accepted
        (the file may be about to be created)."""
        future_path = str(tmp_path / "will_exist_soon.json")
        result = validate_safe_path(future_path)
        # Should resolve to the absolute path
        assert os.path.isabs(result)

    def test_resolves_symlinks(self, tmp_path):
        """Symlinks are resolved to their real target path."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")
        link = tmp_path / "link.txt"
        link.symlink_to(real_file)

        result = validate_safe_path(str(link))
        assert result == str(real_file.resolve())

    # --- allowed_prefixes ---

    def test_allowed_prefixes_accepts_inside(self, tmp_path):
        """Path inside an allowed prefix is accepted."""
        allowed = str(tmp_path / "safe_dir")
        os.makedirs(allowed, exist_ok=True)
        test_file = os.path.join(allowed, "data.json")

        result = validate_safe_path(test_file, allowed_prefixes=[allowed])
        assert result.startswith(os.path.realpath(allowed))

    def test_allowed_prefixes_rejects_outside(self, tmp_path):
        """Path outside all allowed prefixes is rejected."""
        allowed = str(tmp_path / "safe_dir")
        os.makedirs(allowed, exist_ok=True)
        outside = str(tmp_path / "unsafe_dir" / "secret.json")

        with pytest.raises(ValueError, match="outside allowed"):
            validate_safe_path(outside, allowed_prefixes=[allowed])

    def test_empty_allowed_prefixes_rejects_everything(self, tmp_path):
        """An empty allowed_prefixes list means no path can match."""
        test_file = tmp_path / "anything.txt"
        test_file.write_text("test")

        with pytest.raises(ValueError, match="outside allowed"):
            validate_safe_path(str(test_file), allowed_prefixes=[])

    def test_symlink_outside_allowed_prefix_rejected(self, tmp_path):
        """A symlink inside allowed dir pointing outside is rejected
        after resolution."""
        safe_dir = tmp_path / "safe"
        safe_dir.mkdir()
        unsafe_dir = tmp_path / "unsafe"
        unsafe_dir.mkdir()
        real_file = unsafe_dir / "secret.txt"
        real_file.write_text("secret")

        link = safe_dir / "link.txt"
        link.symlink_to(real_file)

        with pytest.raises(ValueError, match="outside allowed"):
            validate_safe_path(str(link), allowed_prefixes=[str(safe_dir)])


# ---------------------------------------------------------------------------
# validate_image_size — in-memory numpy array
# ---------------------------------------------------------------------------


class TestValidateImageSize:
    """Tests for validate_image_size (numpy array check)."""

    def test_accepts_normal_size(self):
        """A normally-sized image passes without error."""
        img = np.zeros((1024, 768, 3), dtype=np.uint8)
        validate_image_size(img)  # should not raise

    def test_rejects_oversized_height(self):
        """Image with height > max_dim is rejected."""
        img = np.zeros((MAX_IMAGE_DIM + 1, 100, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="too large"):
            validate_image_size(img)

    def test_rejects_oversized_width(self):
        """Image with width > max_dim is rejected."""
        img = np.zeros((100, MAX_IMAGE_DIM + 1, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="too large"):
            validate_image_size(img)

    def test_custom_max_dim(self):
        """Custom max_dim is respected."""
        img = np.zeros((500, 500, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="too large"):
            validate_image_size(img, max_dim=256)

    def test_accepts_grayscale(self):
        """2D grayscale image is accepted."""
        img = np.zeros((512, 512), dtype=np.uint8)
        validate_image_size(img)  # should not raise


# ---------------------------------------------------------------------------
# validate_image_path_size — header-only check before decode
# ---------------------------------------------------------------------------


class TestValidateImagePathSize:
    """Tests for validate_image_path_size (PIL header-only check)."""

    def test_accepts_normal_image(self, tmp_path):
        """A small PNG image passes validation."""
        from PIL import Image

        img = Image.new("RGB", (640, 480), color="red")
        path = str(tmp_path / "normal.png")
        img.save(path)

        # Should not raise
        validate_image_path_size(path)

    def test_rejects_oversized_image(self, tmp_path):
        """An image exceeding max_dim is rejected from header alone."""
        # Create a minimal BMP with declared large dimensions but tiny
        # actual data.  BMP header stores dimensions; PIL reads them
        # without decoding pixels.
        path = str(tmp_path / "huge.bmp")
        w, h = MAX_IMAGE_DIM + 100, MAX_IMAGE_DIM + 100
        # Minimal BMP: 14-byte file header + 40-byte DIB header
        row_bytes = (w * 3 + 3) & ~3  # padded to 4-byte boundary
        file_size = 54 + row_bytes * h
        bmp = bytearray(54)
        # BMP magic
        bmp[0:2] = b"BM"
        struct.pack_into("<I", bmp, 2, file_size)
        struct.pack_into("<I", bmp, 10, 54)  # pixel data offset
        # DIB header
        struct.pack_into("<I", bmp, 14, 40)  # header size
        struct.pack_into("<i", bmp, 18, w)
        struct.pack_into("<i", bmp, 22, h)
        struct.pack_into("<H", bmp, 26, 1)   # planes
        struct.pack_into("<H", bmp, 28, 24)  # bits per pixel
        with open(path, "wb") as f:
            f.write(bmp)

        with pytest.raises(ValueError, match="too large"):
            validate_image_path_size(path)

    def test_reads_dimensions_without_full_decode(self, tmp_path):
        """Verify that PIL reads header only — passing a truncated file
        that has a valid header but no pixel data should still allow
        dimension reading."""
        from PIL import Image

        # Create a valid PNG, then truncate it to just the header
        img = Image.new("RGB", (200, 150), color="blue")
        full_path = str(tmp_path / "full.png")
        img.save(full_path)

        # Read the file and keep only first 256 bytes (enough for PNG header)
        with open(full_path, "rb") as f:
            header_bytes = f.read(256)

        truncated_path = str(tmp_path / "truncated.png")
        with open(truncated_path, "wb") as f:
            f.write(header_bytes)

        # Should be able to read dimensions from header without error
        # (PIL reads header lazily; the image is small so it passes)
        validate_image_path_size(truncated_path)

    def test_custom_max_dim(self, tmp_path):
        """Custom max_dim threshold is respected."""
        from PIL import Image

        img = Image.new("RGB", (300, 300), color="green")
        path = str(tmp_path / "medium.png")
        img.save(path)

        with pytest.raises(ValueError, match="too large"):
            validate_image_path_size(path, max_dim=200)

    def test_nonexistent_file_raises(self, tmp_path):
        """A non-existent file path raises FileNotFoundError."""
        path = str(tmp_path / "nope.png")
        with pytest.raises(FileNotFoundError):
            validate_image_path_size(path)
