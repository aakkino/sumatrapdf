/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: Simplified BSD (see COPYING.BSD) */

#include "base/Base.h"
#include "base/File.h"
#include "base/ScopedWin.h"
#include "base/Win.h"

// WinINet from Base.h conflicts with SDK WinHTTP declarations. Declare only the
// WinHTTP bits HttpPostUrl uses. MSVC links winhttp.lib; MinGW links -lwinhttp
// (see cmd/helper/mingw-build.ts).
#if COMPILER_MSVC || COMPILER_MINGW
#ifndef WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY
constexpr DWORD WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY = 4;
#endif
#ifndef WINHTTP_NO_PROXY_NAME
#define WINHTTP_NO_PROXY_NAME ((LPCWSTR) nullptr)
#endif
#ifndef WINHTTP_NO_PROXY_BYPASS
#define WINHTTP_NO_PROXY_BYPASS ((LPCWSTR) nullptr)
#endif
#ifndef WINHTTP_NO_REFERER
#define WINHTTP_NO_REFERER ((LPCWSTR) nullptr)
#endif
#ifndef WINHTTP_DEFAULT_ACCEPT_TYPES
#define WINHTTP_DEFAULT_ACCEPT_TYPES ((LPCWSTR*)nullptr)
#endif
#ifndef WINHTTP_FLAG_SECURE
constexpr DWORD WINHTTP_FLAG_SECURE = 0x00800000;
#endif
#ifndef WINHTTP_FLAG_ASYNC
constexpr DWORD WINHTTP_FLAG_ASYNC = 0x10000000;
#endif
#ifndef WINHTTP_QUERY_STATUS_CODE
constexpr DWORD WINHTTP_QUERY_STATUS_CODE = 19;
#endif
#ifndef WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT
constexpr DWORD WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT = 7;
#endif
#ifndef WINHTTP_OPTION_RECEIVE_TIMEOUT
constexpr DWORD WINHTTP_OPTION_RECEIVE_TIMEOUT = 6;
#endif
#ifndef WINHTTP_OPTION_CONTEXT_VALUE
constexpr DWORD WINHTTP_OPTION_CONTEXT_VALUE = 45;
#endif
#ifndef WINHTTP_QUERY_FLAG_NUMBER
constexpr DWORD WINHTTP_QUERY_FLAG_NUMBER = 0x20000000;
#endif
#ifndef WINHTTP_HEADER_NAME_BY_INDEX
#define WINHTTP_HEADER_NAME_BY_INDEX ((LPCWSTR) nullptr)
#endif
#ifndef WINHTTP_NO_HEADER_INDEX
#define WINHTTP_NO_HEADER_INDEX ((LPDWORD) nullptr)
#endif
constexpr DWORD WINHTTP_CALLBACK_STATUS_HANDLE_CLOSING = 0x00000800;
constexpr DWORD WINHTTP_CALLBACK_STATUS_HEADERS_AVAILABLE = 0x00020000;
constexpr DWORD WINHTTP_CALLBACK_STATUS_READ_COMPLETE = 0x00080000;
constexpr DWORD WINHTTP_CALLBACK_STATUS_REQUEST_ERROR = 0x00200000;
constexpr DWORD WINHTTP_CALLBACK_STATUS_SENDREQUEST_COMPLETE = 0x00400000;
constexpr DWORD WINHTTP_CALLBACK_FLAG_HANDLES = WINHTTP_CALLBACK_STATUS_HANDLE_CLOSING;
constexpr DWORD WINHTTP_CALLBACK_FLAG_HEADERS_AVAILABLE = WINHTTP_CALLBACK_STATUS_HEADERS_AVAILABLE;
constexpr DWORD WINHTTP_CALLBACK_FLAG_READ_COMPLETE = WINHTTP_CALLBACK_STATUS_READ_COMPLETE;
constexpr DWORD WINHTTP_CALLBACK_FLAG_REQUEST_ERROR = WINHTTP_CALLBACK_STATUS_REQUEST_ERROR;
constexpr DWORD WINHTTP_CALLBACK_FLAG_SENDREQUEST_COMPLETE = WINHTTP_CALLBACK_STATUS_SENDREQUEST_COMPLETE;
constexpr DWORD WINHTTP_CALLBACK_FLAGS = WINHTTP_CALLBACK_FLAG_HANDLES | WINHTTP_CALLBACK_FLAG_HEADERS_AVAILABLE |
                                         WINHTTP_CALLBACK_FLAG_READ_COMPLETE | WINHTTP_CALLBACK_FLAG_REQUEST_ERROR |
                                         WINHTTP_CALLBACK_FLAG_SENDREQUEST_COMPLETE;
struct WinHttpAsyncResult {
    DWORD_PTR result;
    DWORD error;
};
using WinHttpStatusCallback = void(WINAPI*)(HINTERNET, DWORD_PTR, DWORD, LPVOID, DWORD);
extern "C" {
HINTERNET WINAPI WinHttpOpen(LPCWSTR, DWORD, LPCWSTR, LPCWSTR, DWORD);
HINTERNET WINAPI WinHttpConnect(HINTERNET, LPCWSTR, INTERNET_PORT, DWORD);
HINTERNET WINAPI WinHttpOpenRequest(HINTERNET, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR, LPCWSTR*, DWORD);
BOOL WINAPI WinHttpSendRequest(HINTERNET, LPCWSTR, DWORD, LPVOID, DWORD, DWORD, DWORD_PTR);
BOOL WINAPI WinHttpReceiveResponse(HINTERNET, LPVOID);
BOOL WINAPI WinHttpQueryHeaders(HINTERNET, DWORD, LPCWSTR, LPVOID, LPDWORD, LPDWORD);
BOOL WINAPI WinHttpQueryDataAvailable(HINTERNET, LPDWORD);
BOOL WINAPI WinHttpReadData(HINTERNET, LPVOID, DWORD, LPDWORD);
BOOL WINAPI WinHttpCloseHandle(HINTERNET);
BOOL WINAPI WinHttpSetOption(HINTERNET, DWORD, LPVOID, DWORD);
BOOL WINAPI WinHttpSetTimeouts(HINTERNET, int, int, int, int);
WinHttpStatusCallback WINAPI WinHttpSetStatusCallback(HINTERNET, WinHttpStatusCallback, DWORD, DWORD_PTR);
}
#endif
#if COMPILER_MSVC
#pragma comment(lib, "winhttp.lib")
#endif

#include "base/Http.h"

// per RFC 1945 10.15 and 3.7, a user agent product token shouldn't contain whitespace
constexpr const WCHAR* kUserAgent = L"SumatraPdfHTTP";

// returns false if failed to download or status code is not 200
// for other scenarios, check HttpRsp
bool HttpGet(Str urlA, HttpRsp* rspOut) {
    logf("HttpGet: url: '%s'\n", urlA);
    HINTERNET hReq = nullptr;
    DWORD infoLevel;
    DWORD headerBuffSize = sizeof(DWORD);
    WCHAR* url = CWStrTemp(urlA);
    // NB: do NOT add INTERNET_FLAG_IGNORE_CERT_CN_INVALID here - it disables TLS
    // hostname validation, letting a network attacker with any trusted cert
    // impersonate our update-check / crash-symbol hosts (GHSA-mjwr-9w29-jp96).
    DWORD flags = INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_RELOAD;

    if (str::StartsWithI(urlA, StrL("https"))) {
        flags |= INTERNET_FLAG_SECURE;
    }

    rspOut->error = ERROR_SUCCESS;
    HINTERNET hInet = InternetOpenW(kUserAgent, INTERNET_OPEN_TYPE_PRECONFIG, nullptr, nullptr, 0);
    if (!hInet) {
        logf("HttpGet: InternetOpen failed\n");
        LogLastError();
        goto Error;
    }

    hReq = InternetOpenUrlW(hInet, url, nullptr, 0, flags, 0);
    if (!hReq) {
        logf("HttpGet: InternetOpenUrl failed\n");
        LogLastError();
        goto Error;
    }

    infoLevel = HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER;
    if (!HttpQueryInfoW(hReq, infoLevel, &rspOut->httpStatusCode, &headerBuffSize, nullptr)) {
        logf("HttpGet: HttpQueryInfoW failed\n");
        LogLastError();
        goto Error;
    }

    for (;;) {
        char buf[1024];
        DWORD dwRead = 0;
        if (!InternetReadFile(hReq, buf, sizeof(buf), &dwRead)) {
            logf("HttpGet: InternetReadFile failed\n");
            LogLastError();
            goto Error;
        }
        if (0 == dwRead) {
            break;
        }
        AtomicIntInc(&gAllowAllocFailure);
        bool ok = rspOut->data.Append(Str(buf, (int)dwRead));
        AtomicIntDec(&gAllowAllocFailure);
        if (!ok) {
            logf("HttpGet: data.Append failed\n");
            goto Error;
        }
    }

Exit:
    if (hReq) {
        InternetCloseHandle(hReq);
    }
    if (hInet) {
        InternetCloseHandle(hInet);
    }
    return IsHttpRspOk(rspOut);

Error:
    rspOut->error = GetLastError();
    if (0 == rspOut->error) {
        rspOut->error = ERROR_GEN_FAILURE;
    }
    goto Exit;
}

// Bounded GET for worker-owned API calls. Unlike HttpGet, it does not log the
// URL because query strings can carry document text or authentication tokens.
bool HttpGetUrl(Str url, HttpRsp* rspOut, const HttpGetOptions& options) {
    HINTERNET hSession = nullptr;
    HINTERNET hConnect = nullptr;
    HINTERNET hRequest = nullptr;
    DWORD statusCode = 0;
    DWORD statusSize = sizeof(statusCode);
    DWORD responseTimeout = 0;
    rspOut->error = ERROR_SUCCESS;
    rspOut->httpStatusCode = (DWORD)-1;
    rspOut->data.Reset();
    if (options.timeoutMs == 0 || options.maxResponseBytes <= 0) {
        rspOut->error = ERROR_INVALID_PARAMETER;
        return false;
    }

    URL_COMPONENTS uc{};
    uc.dwStructSize = sizeof(uc);
    uc.dwSchemeLength = (DWORD)-1;
    uc.dwHostNameLength = (DWORD)-1;
    uc.dwUrlPathLength = (DWORD)-1;
    uc.dwExtraInfoLength = (DWORD)-1;
    WCHAR* urlW = CWStrTemp(url);
    if (!InternetCrackUrlW(urlW, 0, 0, &uc)) {
        rspOut->error = GetLastError();
        return false;
    }

    TempWStr host = str::DupTemp(WStr(uc.lpszHostName, (int)uc.dwHostNameLength));
    TempWStr pathAndQuery = str::DupTemp(WStr(uc.lpszUrlPath, (int)(uc.dwUrlPathLength + uc.dwExtraInfoLength)));
    DWORD flags = 0;
    if (uc.nScheme == INTERNET_SCHEME_HTTPS) {
        flags |= WINHTTP_FLAG_SECURE;
    }

    hSession =
        WinHttpOpen(kUserAgent, WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    responseTimeout = options.timeoutMs;
    if (!WinHttpSetTimeouts(hSession, (int)options.timeoutMs, (int)options.timeoutMs, (int)options.timeoutMs,
                            (int)options.timeoutMs) ||
        !WinHttpSetOption(hSession, WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT, &responseTimeout,
                          sizeof(responseTimeout))) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    hConnect = WinHttpConnect(hSession, host.s, (INTERNET_PORT)uc.nPort, 0);
    if (!hConnect) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    hRequest = WinHttpOpenRequest(hConnect, L"GET", pathAndQuery.s, nullptr, WINHTTP_NO_REFERER,
                                  WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!hRequest) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    if (!WinHttpSetTimeouts(hRequest, (int)options.timeoutMs, (int)options.timeoutMs, (int)options.timeoutMs,
                            (int)options.timeoutMs) ||
        !WinHttpSetOption(hRequest, WINHTTP_OPTION_RECEIVE_TIMEOUT, &responseTimeout, sizeof(responseTimeout)) ||
        !WinHttpSetOption(hRequest, WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT, &responseTimeout,
                          sizeof(responseTimeout))) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    if (!WinHttpSendRequest(hRequest, nullptr, 0, nullptr, 0, 0, 0) || !WinHttpReceiveResponse(hRequest, nullptr)) {
        rspOut->error = GetLastError();
        goto Exit;
    }

    if (!WinHttpQueryHeaders(hRequest, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, nullptr, &statusCode,
                             &statusSize, WINHTTP_NO_HEADER_INDEX)) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    rspOut->httpStatusCode = statusCode;

    for (;;) {
        DWORD available = 0;
        if (!WinHttpQueryDataAvailable(hRequest, &available)) {
            rspOut->error = GetLastError();
            goto Exit;
        }
        if (available == 0) {
            break;
        }
        int remaining = options.maxResponseBytes - len(rspOut->data);
        if (remaining < 0 || available > (DWORD)remaining) {
            rspOut->error = ERROR_FILE_TOO_LARGE;
            goto Exit;
        }
        char buf[4096];
        DWORD toRead = std::min<DWORD>(available, sizeof(buf));
        DWORD read = 0;
        if (!WinHttpReadData(hRequest, buf, toRead, &read)) {
            rspOut->error = GetLastError();
            goto Exit;
        }
        if (read == 0) {
            break;
        }
        if (!rspOut->data.Append(Str(buf, (int)read))) {
            rspOut->error = ERROR_NOT_ENOUGH_MEMORY;
            goto Exit;
        }
    }

Exit:
    if (hRequest) {
        WinHttpCloseHandle(hRequest);
    }
    if (hConnect) {
        WinHttpCloseHandle(hConnect);
    }
    if (hSession) {
        WinHttpCloseHandle(hSession);
    }
    return rspOut->error == ERROR_SUCCESS && rspOut->httpStatusCode >= 200 && rspOut->httpStatusCode < 300;
}

constexpr const int kBufSize = 256 * 1024;

// Download content of a url to a file
bool HttpGetToFile(Str urlA, Str destFilePath, const Func1<HttpProgress*>& cbProgress, i64 maxSize) {
    logf("HttpGetToFile: url: '%s', file: '%s'\n", urlA, destFilePath);
    bool ok = false;
    HINTERNET hReq = nullptr, hInet = nullptr;
    DWORD dwRead = 0;
    DWORD headerBuffSize = sizeof(DWORD);
    DWORD statusCode = 0;
    WCHAR* url = CWStrTemp(urlA);
    char* buf = nullptr;

    HttpProgress progress{};

    WCHAR* pathW = CWStrTemp(destFilePath);
    HANDLE hf =
        CreateFileW(pathW, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (INVALID_HANDLE_VALUE == hf) {
        logf("HttpGetToFile: CreateFileW('%s') failed\n", destFilePath);
        LogLastError();
        goto Exit;
    }

    buf = AllocArray<char>(kBufSize);
    if (!buf) {
        goto Exit;
    }

    hInet = InternetOpenW(kUserAgent, INTERNET_OPEN_TYPE_PRECONFIG, nullptr, nullptr, 0);
    if (!hInet) {
        goto Exit;
    }

    hReq = InternetOpenUrlW(hInet, url, nullptr, 0, 0, 0);
    if (!hReq) {
        goto Exit;
    }

    if (!HttpQueryInfoW(hReq, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &statusCode, &headerBuffSize, nullptr)) {
        goto Exit;
    }

    if (statusCode != 200) {
        goto Exit;
    }

    for (;;) {
        if (!InternetReadFile(hReq, buf, kBufSize, &dwRead)) {
            goto Exit;
        }
        if (dwRead == 0) {
            break;
        }
        if (maxSize >= 0 && progress.nDownloaded > maxSize - (i64)dwRead) {
            goto Exit;
        }
        DWORD size;
        BOOL wroteOk = WriteFile(hf, buf, dwRead, &size, nullptr);
        if (!wroteOk) {
            goto Exit;
        }
        progress.nDownloaded += (i64)dwRead;
        cbProgress.Call(&progress);

        if (size != dwRead) {
            goto Exit;
        }
    }

    ok = true;
Exit:
    CloseHandle(hf);
    if (hReq) {
        InternetCloseHandle(hReq);
    }
    if (hInet) {
        InternetCloseHandle(hInet);
    }
    if (!ok) {
        file::Delete(destFilePath);
    }
    free(buf);
    return ok;
}

bool HttpPost(Str serverA, int port, Str urlA, str::Builder* headers, str::Builder* data) {
    str::Builder resp;
    str::BuilderReserve(nullptr, resp, 2048);
    bool ok = false;
    char* hdr = nullptr;
    DWORD hdrLen = 0;
    HINTERNET hConn = nullptr, hReq = nullptr;
    void* d = nullptr;
    DWORD dLen = 0;
    unsigned int timeoutMs = 15 * 1000;
    DWORD respHttpCode = 0;
    DWORD respHttpCodeSize = sizeof(respHttpCode);
    DWORD dwRead = 0;
    DWORD flags;
    DWORD dwService;
    WCHAR* server = CWStrTemp(serverA);
    WCHAR* url = CWStrTemp(urlA);
    DWORD infoLevel;

    DWORD accessType = INTERNET_OPEN_TYPE_PRECONFIG;
    HINTERNET hInet = InternetOpenW(kUserAgent, accessType, nullptr, nullptr, 0);
    if (!hInet) {
        goto Exit;
    }
    dwService = INTERNET_SERVICE_HTTP;
    hConn = InternetConnectW(hInet, server, (INTERNET_PORT)port, nullptr, nullptr, dwService, 0, 1);
    if (!hConn) {
        goto Exit;
    }

    flags = INTERNET_FLAG_NO_UI;
    if (port == 443) {
        flags |= INTERNET_FLAG_SECURE;
    }
    hReq = HttpOpenRequestW(hConn, L"POST", url, nullptr, nullptr, nullptr, flags, 0);
    if (!hReq) {
        goto Exit;
    }

    if (headers && len(*headers) > 0) {
        hdr = ToStr(*headers).s;
        hdrLen = (DWORD)len(*headers);
    }
    if (data && len(*data) > 0) {
        d = ToStr(*data).s;
        dLen = (DWORD)len(*data);
    }

    InternetSetOptionW(hReq, INTERNET_OPTION_SEND_TIMEOUT, &timeoutMs, sizeof(timeoutMs));
    InternetSetOptionW(hReq, INTERNET_OPTION_RECEIVE_TIMEOUT, &timeoutMs, sizeof(timeoutMs));

    if (!HttpSendRequestA(hReq, hdr, hdrLen, d, dLen)) {
        goto Exit;
    }

    infoLevel = HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER;
    HttpQueryInfoW(hReq, infoLevel, &respHttpCode, &respHttpCodeSize, nullptr);

    do {
        char buf[1024];
        if (!InternetReadFile(hReq, buf, sizeof(buf), &dwRead)) {
            goto Exit;
        }
        ok = resp.Append(Str(buf, (int)dwRead));
        if (!ok) {
            goto Exit;
        }
    } while (dwRead > 0);

#if 0
    // it looks like I should be calling HttpEndRequest(), but it always claims
    // a timeout even though the data has been sent, received and we get HTTP 200
    if (!HttpEndRequest(hReq, nullptr, 0, 0)) {
        LogLastError();
        goto Exit;
    }
#endif
    ok = (200 == respHttpCode);
Exit:
    if (hReq) {
        InternetCloseHandle(hReq);
    }
    if (hConn) {
        InternetCloseHandle(hConn);
    }
    if (hInet) {
        InternetCloseHandle(hInet);
    }
    return ok;
}

//--- URL encoding

// URL-encode s so it can be substituted into a URL, shortening it if the
// encoded form would not fit in maxEncodedLen characters.
TempStr URLEncodeMayTruncateTemp(Str s, int maxEncodedLen, bool* didTruncateOut) {
    if (maxEncodedLen <= 0) {
        maxEncodedLen = kMaxUrlEncodedLen;
    }
    return url::EncodeMayTruncateTemp(s, maxEncodedLen, didTruncateOut);
}

//--- POST with custom headers (WinHTTP)

// Splits "Name: value\nName2: value2" into the CRLF-separated form http wants.
// Also accepts a literal backslash-n: a value that came from a settings file is
// a single line, so that is how a user writes a separator there.
TempStr HttpNormalizeHeadersTemp(Str headers) {
    if (str::IsEmptyOrWhiteSpace(headers)) {
        return {};
    }
    TempStr normalized = str::ReplaceTemp(headers, StrL("\\n"), StrL("\n"));
    str::Builder b;
    StrVec lines;
    Split(&lines, normalized, StrL("\n"), true);
    for (Str line : lines) {
        Str t = str::DupTemp(line);
        str::TrimWSInPlace(t, str::TrimOpt::Both);
        if (str::IsEmptyOrWhiteSpace(t) || !str::Contains(t, StrL(":"))) {
            continue;
        }
        if (len(b) > 0) {
            b.Append(StrL("\r\n"));
        }
        b.Append(t);
    }
    return ToStrTemp(b);
}

constexpr int kHttpPostReadBufferSize = 8 * 1024;

struct AsyncHttpPost {
    HINTERNET request = nullptr;
    HANDLE done = nullptr;
    HANDLE closed = nullptr;
    HttpRsp* response = nullptr;
    int maxResponseBytes = 0;
    char readBuffer[kHttpPostReadBufferSize];
    bool finished = false;
    CRITICAL_SECTION cs;
};

static void AsyncHttpPostFinish(AsyncHttpPost* post, DWORD error) {
    if (post->finished) {
        return;
    }
    post->finished = true;
    post->response->error = error;
    SetEvent(post->done);
}

static void AsyncHttpPostRead(AsyncHttpPost* post) {
    if (WinHttpReadData(post->request, post->readBuffer, dimof(post->readBuffer), nullptr)) {
        return;
    }
    DWORD error = GetLastError();
    if (error != ERROR_IO_PENDING) {
        AsyncHttpPostFinish(post, error);
    }
}

static void AsyncHttpPostHeaders(AsyncHttpPost* post) {
    DWORD size = sizeof(post->response->httpStatusCode);
    if (!WinHttpQueryHeaders(post->request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                             WINHTTP_HEADER_NAME_BY_INDEX, &post->response->httpStatusCode, &size,
                             WINHTTP_NO_HEADER_INDEX)) {
        AsyncHttpPostFinish(post, GetLastError());
        return;
    }
    AsyncHttpPostRead(post);
}

static void AsyncHttpPostReceive(AsyncHttpPost* post) {
    if (WinHttpReceiveResponse(post->request, nullptr)) {
        return;
    }
    DWORD error = GetLastError();
    if (error != ERROR_IO_PENDING) {
        AsyncHttpPostFinish(post, error);
    }
}

static void WINAPI AsyncHttpPostCallback(HINTERNET, DWORD_PTR context, DWORD status, LPVOID data, DWORD dataLen) {
    auto* post = (AsyncHttpPost*)context;
    if (!post) {
        return;
    }
    if (status == WINHTTP_CALLBACK_STATUS_HANDLE_CLOSING) {
        SetEvent(post->closed);
        return;
    }

    EnterCriticalSection(&post->cs);
    if (post->finished) {
        LeaveCriticalSection(&post->cs);
        return;
    }
    if (status == WINHTTP_CALLBACK_STATUS_SENDREQUEST_COMPLETE) {
        AsyncHttpPostReceive(post);
    } else if (status == WINHTTP_CALLBACK_STATUS_HEADERS_AVAILABLE) {
        AsyncHttpPostHeaders(post);
    } else if (status == WINHTTP_CALLBACK_STATUS_READ_COMPLETE) {
        if (dataLen == 0) {
            AsyncHttpPostFinish(post, ERROR_SUCCESS);
        } else if (dataLen > (DWORD)(post->maxResponseBytes - len(post->response->data))) {
            AsyncHttpPostFinish(post, ERROR_FILE_TOO_LARGE);
        } else if (!post->response->data.Append(Str((char*)data, (int)dataLen))) {
            AsyncHttpPostFinish(post, ERROR_NOT_ENOUGH_MEMORY);
        } else {
            AsyncHttpPostRead(post);
        }
    } else if (status == WINHTTP_CALLBACK_STATUS_REQUEST_ERROR) {
        auto* result = (WinHttpAsyncResult*)data;
        AsyncHttpPostFinish(post, result ? result->error : ERROR_GEN_FAILURE);
    }
    LeaveCriticalSection(&post->cs);
}

static void AsyncHttpPostClose(AsyncHttpPost* post) {
    if (!post->request) {
        return;
    }
    EnterCriticalSection(&post->cs);
    LeaveCriticalSection(&post->cs);
    WinHttpCloseHandle(post->request);
    post->request = nullptr;
    WaitForSingleObject(post->closed, INFINITE);
}

// POST body to url with an explicit Content-Type and optional extra headers.
// Blocking, so call it off the ui thread. Returns true on a 2xx; rspOut always
// carries the status code, the body and the win32 error.
//
// Uses WinHTTP rather than the WinINet the rest of this file uses: WinINet
// shares Internet Explorer's cookie jar, so a request would carry whatever
// cookies happen to be lying around to a third-party endpoint. For a call meant
// to be authenticated only by an explicit api key that's a privacy leak.
// blocking; extraHeaders is "Name: value" per line (\n or \r\n separated)
bool HttpPostUrl(Str url, Str contentType, Str extraHeaders, Str body, HttpRsp* rspOut,
                 const HttpPostOptions& options) {
    HINTERNET hSession = nullptr, hConnect = nullptr;
    AsyncHttpPost post;
    bool csInitialized = false;
    bool callbackInstalled = false;
    TempWStr host, pathAndQuery, hdrsW;
    TempStr extra;
    str::Builder hdrs;
    DWORD responseTimeout = 0;
    DWORD_PTR context = 0;
    DWORD wait = 0;
    DWORD flags = 0;
    rspOut->error = ERROR_SUCCESS;
    int timeoutMs = (int)options.timeoutMs;
    if (timeoutMs <= 0 || options.maxResponseBytes <= 0) {
        rspOut->error = ERROR_INVALID_PARAMETER;
        return false;
    }

    // InternetCrackUrl (WinINet) rather than WinHttpCrackUrl: same URL_COMPONENTS,
    // and avoids needing the full winhttp.h URL crack API on MinGW.
    URL_COMPONENTS uc{};
    uc.dwStructSize = sizeof(uc);
    uc.dwSchemeLength = (DWORD)-1;
    uc.dwHostNameLength = (DWORD)-1;
    uc.dwUrlPathLength = (DWORD)-1;
    uc.dwExtraInfoLength = (DWORD)-1;
    WCHAR* urlW = CWStrTemp(url);
    if (!InternetCrackUrlW(urlW, 0, 0, &uc)) {
        rspOut->error = GetLastError();
        return false;
    }

    host = str::DupTemp(WStr(uc.lpszHostName, (int)uc.dwHostNameLength));
    pathAndQuery = str::DupTemp(WStr(uc.lpszUrlPath, (int)(uc.dwUrlPathLength + uc.dwExtraInfoLength)));
    InitializeCriticalSection(&post.cs);
    csInitialized = true;
    post.done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    post.closed = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    post.response = rspOut;
    post.maxResponseBytes = options.maxResponseBytes;
    if (!post.done || !post.closed) {
        rspOut->error = GetLastError();
        goto Exit;
    }

    hSession = WinHttpOpen(kUserAgent, WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME,
                           WINHTTP_NO_PROXY_BYPASS, WINHTTP_FLAG_ASYNC);
    if (!hSession) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    responseTimeout = (DWORD)timeoutMs;
    if (!WinHttpSetTimeouts(hSession, timeoutMs, timeoutMs, timeoutMs, timeoutMs) ||
        !WinHttpSetOption(hSession, WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT, &responseTimeout,
                          sizeof(responseTimeout))) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    hConnect = WinHttpConnect(hSession, host.s, (INTERNET_PORT)uc.nPort, 0);
    if (!hConnect) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    flags = (uc.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
    post.request = WinHttpOpenRequest(hConnect, L"POST", pathAndQuery.s, nullptr, WINHTTP_NO_REFERER,
                                      WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!post.request) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    if (!WinHttpSetTimeouts(post.request, timeoutMs, timeoutMs, timeoutMs, timeoutMs) ||
        !WinHttpSetOption(post.request, WINHTTP_OPTION_RECEIVE_TIMEOUT, &responseTimeout, sizeof(responseTimeout)) ||
        !WinHttpSetOption(post.request, WINHTTP_OPTION_RECEIVE_RESPONSE_TIMEOUT, &responseTimeout,
                          sizeof(responseTimeout))) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    context = (DWORD_PTR)&post;
    if (!WinHttpSetOption(post.request, WINHTTP_OPTION_CONTEXT_VALUE, &context, sizeof(context))) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    if (WinHttpSetStatusCallback(post.request, AsyncHttpPostCallback, WINHTTP_CALLBACK_FLAGS, 0) ==
        (WinHttpStatusCallback)-1) {
        rspOut->error = GetLastError();
        goto Exit;
    }
    callbackInstalled = true;

    if (!str::IsEmptyOrWhiteSpace(contentType)) {
        hdrs.Append(fmt("Content-Type: %s", contentType));
    }
    extra = HttpNormalizeHeadersTemp(extraHeaders);
    if (!str::IsEmptyOrWhiteSpace(extra)) {
        if (len(hdrs) > 0) {
            hdrs.Append(StrL("\r\n"));
        }
        hdrs.Append(extra);
    }
    hdrsW = ToWStrTemp(ToStr(hdrs));
    if (!WinHttpSendRequest(post.request, hdrsW.s, (DWORD)-1, (void*)body.s, (DWORD)len(body), (DWORD)len(body),
                            context)) {
        DWORD error = GetLastError();
        if (error != ERROR_IO_PENDING) {
            rspOut->error = error;
            goto Exit;
        }
    }

    wait = WaitForSingleObject(post.done, (DWORD)timeoutMs);
    if (wait != WAIT_OBJECT_0) {
        EnterCriticalSection(&post.cs);
        AsyncHttpPostFinish(&post, wait == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError());
        LeaveCriticalSection(&post.cs);
    }

Exit:
    if (post.request) {
        if (callbackInstalled) {
            AsyncHttpPostClose(&post);
        } else {
            WinHttpCloseHandle(post.request);
        }
    }
    if (hConnect) {
        WinHttpCloseHandle(hConnect);
    }
    if (hSession) {
        WinHttpCloseHandle(hSession);
    }
    if (post.done) {
        CloseHandle(post.done);
    }
    if (post.closed) {
        CloseHandle(post.closed);
    }
    if (csInitialized) {
        DeleteCriticalSection(&post.cs);
    }
    return rspOut->error == ERROR_SUCCESS && rspOut->httpStatusCode >= 200 && rspOut->httpStatusCode < 300;
}
