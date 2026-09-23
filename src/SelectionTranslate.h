/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

struct WindowTab;
struct MainWindow;

enum class TranslateEngine {
    Default = 0, // engine remembered in settings (TranslateEngine), Google if none
    Google,
    DeepL,
    Grok,
    Claude,
    Codex,
    AntiGravity,
};

void ShowSelectionTranslateDialog(WindowTab* tab, TranslateEngine engine);
void ShowSelectionTranslatePopup(WindowTab* tab);
bool HasSelectionTranslatePopup(MainWindow* win);
void UpdateSelectionTranslatePopup(MainWindow* win);
void RepositionTranslatePopup(MainWindow* win);
void OnTranslateSelectionChanged(MainWindow* win);
void CloseTranslatePopupForTab(WindowTab* tab);

TempStr SelectionTranslateResultTemp(int backend, Str srcLang, Str dstLang, Str text, int* exitCode);
TempStr SelectionTranslatePopupTestTemp(Str action, Str value, int* exitCode);
