# Windows Build

## Scenario: MSVC WinINet and WinHTTP Compatibility

### 1. Scope / Trigger

- Trigger: `src/base/Win.cpp` uses MSVC `__cpuid`; `Base.h` includes WinINet
  before `Http_win.cpp` needs a small WinHTTP API subset.
- Keep `Base.h` first, leave `_WIN32_WINNT` and project files unchanged, and do
  not change HTTP behavior or popup code.

### 2. Signatures

```cpp
#if COMPILER_MSVC
#include <intrin.h>
#endif

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
}
```

- The narrow declarations and constants in `Http_win.cpp` apply under
  `COMPILER_MSVC || COMPILER_MINGW`. MSVC retains
  `#pragma comment(lib, "winhttp.lib")`; MinGW retains its existing linker path.

### 3. Contracts

- `<intrin.h>` is the compiler-owned declaration source for every MSVC
  `__cpuid` call. Do not hand-declare compiler intrinsics.
- `base/Base.h` remains first and brings in `wininet.h`. `Http_win.cpp` must not
  include `winhttp.h` after it: SDKs redeclare `URL_COMPONENTS`,
  `INTERNET_SCHEME`, `HTTP_VERSION_INFO`, `BOOLAPI`, and security flags.
- `HttpPostUrl()` continues using WinINet `InternetCrackUrlW` plus the declared
  WinHTTP open/connect/request/send/receive/query/read/close subset. Any new
  WinHTTP API requires an ABI-identical narrow declaration or an isolated
  include boundary.
- Required VS component: `Microsoft.VisualStudio.Component.Windows11SDK.22621`.
  For a process needing that SDK, temporarily set
  `WindowsTargetPlatformVersion=10.0.22621.0`; do not commit that override to a
  project file.

### 4. Validation & Error Matrix

| Condition                           | Required response                                                           |
| ----------------------------------- | --------------------------------------------------------------------------- |
| MSVC reports `__cpuid` undeclared   | Include `<intrin.h>` in `Win.cpp` under `COMPILER_MSVC`.                    |
| WinINet/WinHTTP redefinitions       | Keep `Base.h` first; use narrow declarations, never `winhttp.h`.            |
| WinHTTP unresolved external on MSVC | Retain `#pragma comment(lib, "winhttp.lib")`.                               |
| SDK 22621 not found                 | Install the required VS component; set the temporary SDK environment value. |
| Need another WinHTTP symbol         | Add its exact ABI declaration and rebuild base before use.                  |

### 5. Good / Base / Bad Cases

- Good: Debug/x64 compiles `Win.cpp` with MSVC intrinsics and `Http_win.cpp`
  with the narrow WinHTTP surface.
- Base: `HttpPostUrl()` still parses with WinINet and links `winhttp.lib` on
  MSVC; MinGW behavior is unchanged.
- Bad: adding `#include <winhttp.h>` after `Base.h`, hand-writing `__cpuid`, or
  changing global SDK/project settings to hide the conflict.

### 6. Tests Required

- Run:

  ```powershell
  msbuild vs2022/base.vcxproj /t:Build /p:Configuration=Debug /p:Platform=x64
  ```

  Assert both affected translation units compile and link.

- Run `bun cmd/build.ts -debug`; assert the normal debug build integrates the
  base library without changing UI behavior.
- When extending the declaration block, review every parameter and return type
  against the selected SDK declaration before the focused builds.

### 7. Wrong vs Correct

#### Wrong

```cpp
#include "base/Base.h"
#include <winhttp.h>
```

The WinINet-first base include conflicts with SDK WinHTTP types.

#### Correct

```cpp
#include "base/Base.h"

#if COMPILER_MSVC || COMPILER_MINGW
// Declare only the WinHTTP API used here.
#endif
```

Keep the boundary narrow and preserve the MSVC link directive.
