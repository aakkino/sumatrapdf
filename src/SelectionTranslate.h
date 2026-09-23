/* Copyright 2022 the SumatraPDF project authors (see AUTHORS file).
   License: GPLv3 */

struct WindowTab;
struct MainWindow;

void ShowSelectionTranslatePopup(WindowTab* tab);
bool HasSelectionTranslatePopup(MainWindow* win);
void UpdateSelectionTranslatePopup(MainWindow* win);
void RepositionTranslatePopup(MainWindow* win);
void OnTranslateSelectionChanged(MainWindow* win);
void CloseTranslatePopupForTab(WindowTab* tab);

TempStr SelectionTranslatePopupTestTemp(Str action, Str value, int* exitCode);
