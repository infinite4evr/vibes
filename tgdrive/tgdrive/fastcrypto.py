"""Native AES for Telethon where `cryptg` isn't available (the Android app).

Every byte TG Drive moves is AES-encrypted by Telethon: IGE for MTProto, CTR for files served by
Telegram's CDNs and for MTProto proxies. Telethon uses `cryptg` for IGE when it's installed and
otherwise pure Python (about 1 MB/s on a phone; streaming video needs far more). `cryptg` is
Rust with no Android build, but the Python runtime there ships OpenSSL 3's libcrypto, which has
both modes in native code. install() points Telethon at it.

Copies go through ctypes buffers made with from_buffer_copy (one memcpy), not the per-byte
unpacking Telethon's own libssl helper uses, which costs more than the encryption itself.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from typing import Optional

log = logging.getLogger("tgdrive.crypto")

_AES_MAXNR = 14


class _AESKey(ctypes.Structure):
    _fields_ = [("rd_key", ctypes.c_uint32 * (4 * (_AES_MAXNR + 1))), ("rounds", ctypes.c_uint)]


_LIB_NAMES = ("libcrypto_python.so", "libcrypto_chaquopy.so", "libcrypto.so.3", "libcrypto.so")


def load_libcrypto() -> Optional[ctypes.CDLL]:
    """OpenSSL's libcrypto with the AES functions this module needs, or None."""
    names = [os.environ.get("TGDRIVE_LIBCRYPTO") or "", *_LIB_NAMES, ctypes.util.find_library("crypto") or ""]
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            for sym in ("AES_set_encrypt_key", "AES_set_decrypt_key", "AES_ige_encrypt", "EVP_CIPHER_CTX_new",
                        "EVP_aes_256_ctr", "EVP_EncryptInit_ex", "EVP_EncryptUpdate", "EVP_CIPHER_CTX_free"):
                getattr(lib, sym)
        except (OSError, AttributeError):
            continue
        _declare(lib)
        return lib
    return None


def _declare(lib: ctypes.CDLL) -> None:
    lib.AES_set_encrypt_key.argtypes = lib.AES_set_decrypt_key.argtypes = [
        ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(_AESKey)]
    lib.AES_set_encrypt_key.restype = lib.AES_set_decrypt_key.restype = ctypes.c_int
    lib.AES_ige_encrypt.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(_AESKey),
                                    ctypes.c_void_p, ctypes.c_int]
    lib.AES_ige_encrypt.restype = None
    lib.EVP_CIPHER_CTX_new.argtypes = []
    lib.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
    lib.EVP_aes_256_ctr.argtypes = []
    lib.EVP_aes_256_ctr.restype = ctypes.c_void_p
    lib.EVP_EncryptInit_ex.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                                       ctypes.c_char_p]
    lib.EVP_EncryptInit_ex.restype = ctypes.c_int
    lib.EVP_EncryptUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                      ctypes.c_void_p, ctypes.c_int]
    lib.EVP_EncryptUpdate.restype = ctypes.c_int
    lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
    lib.EVP_CIPHER_CTX_free.restype = None


class IGE:
    """AES-256-IGE with Telethon's (data, key, iv32) calling convention."""

    def __init__(self, lib: ctypes.CDLL):
        self.lib = lib

    def _run(self, data: bytes, key: bytes, iv: bytes, encrypt: bool) -> bytes:
        n = len(data)
        if n % 16:
            raise ValueError("IGE data must be a multiple of 16 bytes")
        if len(iv) != 32:
            raise ValueError("IGE needs a 32-byte IV")
        k = _AESKey()
        setter = self.lib.AES_set_encrypt_key if encrypt else self.lib.AES_set_decrypt_key
        if setter(bytes(key), 8 * len(key), ctypes.byref(k)) != 0:
            raise ValueError("bad AES key")
        src = (ctypes.c_char * n).from_buffer_copy(data)
        dst = ctypes.create_string_buffer(n)
        ivb = ctypes.create_string_buffer(bytes(iv), 32)   # AES_ige_encrypt updates the IV in place
        self.lib.AES_ige_encrypt(src, dst, n, ctypes.byref(k), ivb, 1 if encrypt else 0)
        return dst.raw

    def encrypt(self, data: bytes, key: bytes, iv: bytes) -> bytes:
        pad = len(data) % 16
        if pad:   # Telethon pads with random bytes itself; keep its behaviour for direct callers
            data = bytes(data) + os.urandom(16 - pad)
        return self._run(data, key, iv, True)

    def decrypt(self, data: bytes, key: bytes, iv: bytes) -> bytes:
        return self._run(data, key, iv, False)


def _ctr_class(lib: ctypes.CDLL):
    cipher = lib.EVP_aes_256_ctr()

    class NativeCTR:
        """Drop-in for telethon.crypto.AESModeCTR: a running AES-256-CTR stream."""

        def __init__(self, key: bytes, iv: bytes):
            assert isinstance(key, bytes) and len(key) == 32
            assert isinstance(iv, bytes) and len(iv) == 16
            self._ctx = lib.EVP_CIPHER_CTX_new()
            if not self._ctx or lib.EVP_EncryptInit_ex(self._ctx, cipher, None, key, iv) != 1:
                raise RuntimeError("OpenSSL couldn't start AES-CTR")

        def encrypt(self, data: bytes) -> bytes:
            n = len(data)
            if not n:
                return b""
            src = (ctypes.c_char * n).from_buffer_copy(data)
            dst = ctypes.create_string_buffer(n)
            outl = ctypes.c_int(0)
            if lib.EVP_EncryptUpdate(self._ctx, dst, ctypes.byref(outl), src, n) != 1 or outl.value != n:
                raise RuntimeError("AES-CTR failed")
            return dst.raw

        decrypt = encrypt

        def __del__(self):
            ctx, self._ctx = getattr(self, "_ctx", None), None
            if ctx:
                lib.EVP_CIPHER_CTX_free(ctx)

    return NativeCTR


_installed: Optional[str] = None


def install() -> str:
    """Make Telethon encrypt natively. Returns what it uses: cryptg, openssl or python."""
    global _installed
    if _installed:
        return _installed
    from telethon.crypto import aes as t_aes
    from telethon.crypto import aesctr as t_ctr
    lib = load_libcrypto()
    if lib is not None:
        ctr = _ctr_class(lib)
        t_ctr.AESModeCTR.__init__ = ctr.__init__
        t_ctr.AESModeCTR.encrypt = ctr.encrypt
        t_ctr.AESModeCTR.decrypt = ctr.decrypt
        t_ctr.AESModeCTR.__del__ = ctr.__del__
    if t_aes.cryptg:
        _installed = "cryptg"
    elif lib is not None:
        ige = IGE(lib)
        t_aes.libssl.encrypt_ige = ige.encrypt
        t_aes.libssl.decrypt_ige = ige.decrypt
        _installed = "openssl"
    else:
        _installed = "python"
        log.warning("no native AES found: Telegram transfers will be slow")
    log.info("encryption: %s%s", _installed, " (+ OpenSSL AES-CTR)" if lib is not None else "")
    return _installed
