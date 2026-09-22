/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: Simplified BSD (see COPYING.BSD) */

struct HttpRsp {
    Str url;
    str::Builder data;
    DWORD error = (DWORD)-1;
    DWORD httpStatusCode = (DWORD)-1;

    HttpRsp() = default;
    ~HttpRsp();
};

struct HttpProgress {
    i64 nDownloaded;
};

bool IsHttpRspOk(const HttpRsp*);

bool HttpPost(Str server, int port, Str url, str::Builder* headers, str::Builder* data);
bool HttpGet(Str url, HttpRsp* rspOut);
bool HttpGetToFile(Str url, Str destFilePath, const Func1<HttpProgress*>& cbProgress, i64 maxSize = -1);

constexpr DWORD kHttpPostDefaultTimeoutMs = 15 * 1000;
constexpr int kHttpPostDefaultMaxResponseBytes = 1024 * 1024;

struct HttpGetOptions {
    DWORD timeoutMs = kHttpPostDefaultTimeoutMs;
    int maxResponseBytes = kHttpPostDefaultMaxResponseBytes;
};

bool HttpGetUrl(Str url, HttpRsp* rspOut, const HttpGetOptions& options = {});

struct HttpPostOptions {
    DWORD timeoutMs = kHttpPostDefaultTimeoutMs;
    int maxResponseBytes = kHttpPostDefaultMaxResponseBytes;
};

bool HttpPostUrl(Str url, Str contentType, Str extraHeaders, Str body, HttpRsp* rspOut,
                 const HttpPostOptions& options = {});
TempStr HttpNormalizeHeadersTemp(Str headers);

// How much URL-encoded text we're willing to put in a URL. ShellExecuteW hands
// the URL to the browser as a command line, so the hard ceiling is
// CreateProcess's 32767 WCHARs; browsers give up well before that and each has
// its own limit, so stay comfortably below.
constexpr int kMaxUrlEncodedLen = 8192;

TempStr URLEncodeMayTruncateTemp(Str s, int maxEncodedLen = 0, bool* didTruncateOut = nullptr);
