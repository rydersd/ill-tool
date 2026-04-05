/**
 * ai_unicode_string_stub.cpp — Minimal implementation of ai::UnicodeString.
 *
 * The real ai::UnicodeString is implemented inside the Illustrator application.
 * This stub provides only the symbols needed for linking during development builds.
 * At runtime inside Illustrator, the host's real implementation is used.
 *
 * We define CAIUnicodeStringImpl here as a simple wrapper around std::string.
 * Only non-inline methods that are actually needed at link time are implemented.
 */

#include "IAIUnicodeString.h"
#include <cstring>
#include <string>

/* ========================================================================== */
/*  CAIUnicodeStringImpl — minimal internal storage                           */
/* ========================================================================== */

class CAIUnicodeStringImpl {
public:
    std::string fData;

    CAIUnicodeStringImpl() = default;
    explicit CAIUnicodeStringImpl(const char* s) : fData(s ? s : "") {}
    CAIUnicodeStringImpl(const char* s, size_t len) : fData(s, len) {}
};

/* ========================================================================== */
/*  ai::UnicodeString — only non-inline methods                               */
/* ========================================================================== */

namespace ai {

/* Static member: npos */
const UnicodeString::size_type UnicodeString::npos = static_cast<size_type>(-1);

/* Default constructor */
UnicodeString::UnicodeString() AINOTHROW
    : fImpl(new CAIUnicodeStringImpl())
{
}

/* Construct from encoded byte array with length */
UnicodeString::UnicodeString(const char* string, offset_type srcByteLen,
    AICharacterEncoding /*encoding*/)
    : fImpl(new CAIUnicodeStringImpl(string, static_cast<size_t>(srcByteLen)))
{
}

/* Construct from 0-terminated C string */
UnicodeString::UnicodeString(const char* string, AICharacterEncoding /*encoding*/)
    : fImpl(new CAIUnicodeStringImpl(string))
{
}

/* Construct from std::string */
UnicodeString::UnicodeString(const std::string& string, AICharacterEncoding /*encoding*/)
    : fImpl(new CAIUnicodeStringImpl(string.c_str(), string.size()))
{
}

/* Construct from ASUnicode* (null-terminated UTF-16) — stub: stores empty */
UnicodeString::UnicodeString(const ASUnicode* /*string*/)
    : fImpl(new CAIUnicodeStringImpl())
{
}

/* Construct from ASUnicode* with count — stub: stores empty */
UnicodeString::UnicodeString(const ASUnicode* /*string*/, size_type /*srcUTF16Count*/)
    : fImpl(new CAIUnicodeStringImpl())
{
}

/* Construct from basic_string<ASUnicode> — stub: stores empty */
UnicodeString::UnicodeString(const std::basic_string<ASUnicode>& /*string*/)
    : fImpl(new CAIUnicodeStringImpl())
{
}

/* Construct from ZRef — stub: stores empty */
UnicodeString::UnicodeString(const ZRef /*zStringKey*/)
    : fImpl(new CAIUnicodeStringImpl())
{
}

/* Construct from count copies of UTF32 char — stub */
UnicodeString::UnicodeString(size_type count, UTF32TextChar ch)
    : fImpl(new CAIUnicodeStringImpl())
{
    if (ch < 128) {
        fImpl->fData.assign(count, static_cast<char>(ch));
    }
}

/* Construct from impl pointer */
UnicodeString::UnicodeString(CAIUnicodeStringImpl* impl)
    : fImpl(impl)
{
}

/* Copy constructor */
UnicodeString::UnicodeString(const UnicodeString& s)
    : fImpl(new CAIUnicodeStringImpl())
{
    if (s.fImpl) {
        fImpl->fData = s.fImpl->fData;
    }
}

/* Destructor */
UnicodeString::~UnicodeString()
{
    delete fImpl;
    fImpl = nullptr;
}

/* Copy assignment */
UnicodeString& UnicodeString::operator=(const UnicodeString& rhs)
{
    if (this != &rhs) {
        if (!fImpl) fImpl = new CAIUnicodeStringImpl();
        if (rhs.fImpl) {
            fImpl->fData = rhs.fImpl->fData;
        } else {
            fImpl->fData.clear();
        }
    }
    return *this;
}

/* ========================================================================== */
/*  ai::SPAlloc — stub for AutoBuffer allocation                              */
/* ========================================================================== */

void* SPAlloc::AllocateBlock(size_t byteCount)
{
    return ::operator new(byteCount);
}

void SPAlloc::DeleteBlock(void* block)
{
    ::operator delete(block);
}

} // namespace ai
