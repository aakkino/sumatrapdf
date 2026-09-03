# Research: toolchain source compatibility

- Query: Identify minimal source fixes for MSVC 14.44 / Windows SDK 10.0.22000.0 baseline failures without changing selection-popup behavior.
- Scope: internal
- Date: 2026-09-03

## Findings

### `__cpuid` undeclared

Files found:

- `src/base/Win.cpp` - x86/x64 CPU feature detection.
- `src/base/Base.h` - first project include and Windows SDK include owner.
- `vs2022/base.vcxproj` - compiles `Win.cpp` and sets `Debug|x64` defines.

Include chain and cause:

1. `src/base/Win.cpp:4` includes `base/Base.h`; its local includes at
   `src/base/Win.cpp:11-18` add `aclapi.h`, `bitset`, `cpuid.h` only for
   MinGW, `float.h`, and `mlang.h`.
2. The MSVC branch invokes `__cpuid(cpuInfo, ...)` at
   `src/base/Win.cpp:3750`, `:3757`, and `:3766`.
3. No MSVC intrinsic header is included. MSVC 14.44's
   `VC/Tools/MSVC/14.44.35207/include/intrin.h:198-199` declares
   `__cpuid` and `__cpuidex`. The SDK's `um/winnt.h` includes `intrin.h`
   only in its ARM/ARM64 sections (lines 4503-4508 and 5361-5365), not for
   this x64 path.
4. `vs2022/base.vcxproj:398-418` selects the x64 configuration, has
   `/WX`, and defines neither an intrinsic declaration nor an include that
   would supply one. `Win.cpp` is compiled by `base.vcxproj:985`.

Minimal source fix:

- Own `src/base/Win.cpp` only. Add `#include <intrin.h>` under
  `#if COMPILER_MSVC`, adjacent to the existing MinGW-only
  `#include <cpuid.h>` at `src/base/Win.cpp:13-15`.
- Do not add a declaration by hand and do not change project/SDK settings.
  The compiler-owned header carries the supported signature and intrinsic
  treatment. It is harmless for ARM64 because this function returns before
  the x86 `__cpuid` branch (`src/base/Win.cpp:3725-3738`).

Repository precedent:

- Commit `58b565c21` added the adjacent MinGW `cpuid.h` include and split
  the MinGW and MSVC intrinsic call forms. The current source preserves that
  shape at `src/base/Win.cpp:13-15` and `:3747-3766`.

### WinINet / WinHTTP collisions

Files found:

- `src/base/Base.h` - globally includes WinINet.
- `src/base/Http_win.cpp` - only product translation unit that includes
  WinHTTP and only caller of the required WinHTTP API subset.
- `vs2022/base.vcxproj` - compiles `Http_win.cpp` at `:974` with
  `UNICODE`, `_WIN32_WINNT=0x0601`, and `/WX` at `:398-418`.

Actual source path and conflicting declarations:

1. `src/base/Http_win.cpp:4` includes `base/Base.h` first, as required by
   project convention. `Base.h:131-146` includes `winsock2.h`, `windows.h`,
   then `wininet.h` at `:142`.
2. `Http_win.cpp:56` then includes `winhttp.h` on MSVC. Thus the failure is
   the ordered pair `wininet.h -> winhttp.h` in one translation unit, not a
   transitive dependency from the selection-popup paths.
3. SDK 10.0.22000.0 `um/wininet.h:59` defines `BOOLAPI`; `:284-304` defines
   enum `INTERNET_SCHEME`; `:479-485` defines `HTTP_VERSION_INFO`; `:522-582`
   defines `URL_COMPONENTS`; and `:1331-1332` defines the two
   `SECURITY_FLAG_IGNORE_CERT_*` names.
4. The same SDK's `um/winhttp.h:47` redefines `BOOLAPI`; `:81-88` redefines
   the certificate flags; `:112-116` redefines `HTTP_VERSION_INFO`; `:123-128`
   redeclares `INTERNET_SCHEME` as `int`; and `:150-170` redeclares
   `URL_COMPONENTS`. The latter type conflicts are hard C++ errors; macro
   diagnostics are elevated by the project configuration.
5. `HttpPostUrl()` needs only `WinHttpOpen`, `Connect`, `OpenRequest`,
   `SendRequest`, `ReceiveResponse`, `QueryHeaders`, `QueryDataAvailable`,
   `ReadData`, and `CloseHandle` (`src/base/Http_win.cpp:389-460`). URL
   parsing intentionally uses the existing WinINet `InternetCrackUrlW` and
   its `URL_COMPONENTS` (`:371-400`). It does not need any WinHTTP URL type.

Minimal source fix:

- Own `src/base/Http_win.cpp` only. Make its existing narrow WinHTTP
  declarations/constants block at `:13-54` apply to MSVC as well as MinGW;
  remove the `#include <winhttp.h>` branch at `:55-58`; retain
  `#pragma comment(lib, "winhttp.lib")` for MSVC outside the narrow-declaration
  block. Keep the existing MinGW linker arrangement unchanged.
- Update the nearby comment to say the WinINet-first Base include conflicts
  with SDK WinHTTP declarations, so this file declares only the APIs it uses.
  The existing `f64e7d41a` MinGW workaround is the direct repository
  precedent. Its current comment's claim that MSVC headers are compatible is
  disproven by this SDK revision.
- Do not reorder or remove `Base.h`'s `wininet.h`: it is a broad base-header
  contract, and `Http_win.cpp` needs its `InternetCrackUrlW`, `URL_COMPONENTS`,
  `INTERNET_SCHEME_HTTPS`, `HINTERNET`, and `INTERNET_PORT` at
  `src/base/Http_win.cpp:371-400`. Do not alter `_WIN32_WINNT` or SDK version.

Risk:

- The handwritten declarations must remain ABI-identical to the imported
  WinHTTP functions. The existing MinGW block already has this exact API
  footprint. Future use of any other WinHTTP API must either extend this
  narrow block or isolate WinHTTP from the WinINet-bearing base include.

### Host architecture

`HostX86\\x64` is normal MSBuild tool selection: the x86-hosted compiler emits
x64 objects. The project itself selects `Debug|x64` at
`vs2022/base.vcxproj:398-418`. Nothing in the source include chain branches on
the compiler host architecture; both failures arise before code generation
from missing/conflicting declarations. No host-toolset change is indicated.

## Focused Verification

Run after the two edits (not run during this research):

```powershell
msbuild vs2022/base.vcxproj /t:Build /p:Configuration=Debug /p:Platform=x64
bun cmd/build.ts -debug
```

The first command compiles both affected translation units in the failing
project. The second verifies normal application integration. No behavioral
test is needed for this compatibility-only unit; it must not change the
selection-translation popup.

## Related Specs

- `AGENTS.md` - `base/Base.h` must be first in `.cpp` include order; changed
  C++ sources require clang-format before a build.
- `.trellis/tasks/09-03-selection-translation-popup/implement.md` - this is
  an independent compatibility unit and must not extend popup ownership.

## Caveats / Not Found

- No product source besides `src/base/Http_win.cpp` includes `winhttp.h`.
- The report is source/header inspection only; it intentionally did not run a
  build, test, formatter, or modify product code.
