
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from conduit.environment import environment_service
from conduit.model_advisor import ollama_catalog
from conduit.providers.gemini import GeminiProvider
from conduit.providers.openai import OpenAIProvider
from conduit.providers.grok import GrokProvider
from conduit.providers.console_recovery import _choose_openai_model, _choose_grok_model
from conduit.providers.ollama import OllamaProvider
from conduit.core.models import ChatMessage, Role
from .app import APP_QSS, OllamaModelDialog, run_gui
from .theme import TEXT, MUTED, YELLOW, PURPLE, CYAN


async def _validate_cloud(provider: str, api_key: str) -> tuple[str, object]:
    if provider == "gemini":
        candidate = GeminiProvider(api_key=api_key)
        models = await candidate.list_models()
        preferred = "gemini-flash-latest"
        model = (
            preferred if preferred in models
            else next((m for m in models if "flash" in m.casefold()), models[0] if models else "")
        )
    elif provider == "openai":
        candidate = OpenAIProvider(api_key=api_key)
        models = await candidate.list_models()
        model = _choose_openai_model(models)
    elif provider == "grok":
        candidate = GrokProvider(api_key=api_key)
        models = await candidate.list_models()
        model = _choose_grok_model(models)
    else:
        raise RuntimeError(f"Unsupported cloud provider: {provider}")

    if not model:
        await candidate.close()
        raise RuntimeError(f"No usable {provider} model was available to this key.")

    try:
        response = await candidate.chat(
            [ChatMessage(Role.USER, "Reply with OK only.")],
            model=model,
        )
        if not response.text.strip():
            raise RuntimeError("Provider returned an empty validation response.")
    finally:
        await candidate.close()

    return model, candidate


def _installed_ollama_models() -> list[str]:
    exe = environment_service.ollama_executable()
    if not exe:
        return []
    try:
        result = subprocess.run(
            [exe, "list"],
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            return []
        rows = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if line:
                rows.append(line.split()[0])
        return rows
    except Exception:
        return []


class ProviderStartupDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conduit — Choose AI Provider")
        self.setMinimumWidth(560)
        self.selected: tuple[str, str] | None = None

        layout = QVBoxLayout(self)
        title = QLabel("CHOOSE CONDUIT'S AI PROVIDER")
        title.setStyleSheet(f"color:{YELLOW};font-size:15px;font-weight:800;")
        layout.addWidget(title)

        note = QLabel(
            "You can switch providers later from the buttons below the chat. "
            "API keys are masked and kept only in memory for this run."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{MUTED};font-size:10px;")
        layout.addWidget(note)

        for provider, caption, detail in (
            ("ollama", "OLLAMA", "Local • Offline • Runs models on your PC"),
            ("gemini", "GEMINI", "Cloud • General • Vision"),
            ("openai", "OPENAI", "Cloud • General • Coding"),
            ("grok", "GROK AI", "Cloud • General • Reasoning"),
        ):
            button = QPushButton(f"{caption}\n{detail}")
            button.setMinimumHeight(54)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, p=provider: self.choose(p))
            layout.addWidget(button)

        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def choose(self, provider: str) -> None:
        if provider == "ollama":
            self._choose_ollama()
            return

        names = {"gemini": "Gemini", "openai": "OpenAI", "grok": "Grok AI"}
        name = names[provider]
        key, ok = QInputDialog.getText(
            self,
            f"Connect to {name}",
            f"Enter your {name} API key:",
            QLineEdit.Password,
        )
        if not ok:
            return
        key = key.strip()
        if not key:
            QMessageBox.warning(self, name, "No API key was entered.")
            return

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            model, _ = asyncio.run(_validate_cloud(provider, key))
        except Exception as exc:
            QMessageBox.critical(self, f"{name} Connection Failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        env_name = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "grok": "XAI_API_KEY",
        }[provider]
        os.environ[env_name] = key
        if provider == "gemini":
            os.environ["CONDUIT_GEMINI_SEARCH_MODEL"] = model
        self.selected = (provider, model)
        self.accept()

    def _choose_ollama(self) -> None:
        status = environment_service.verify_ollama()
        if not status.available:
            box = QMessageBox(self)
            box.setWindowTitle("Ollama is not installed")
            box.setIcon(QMessageBox.Information)
            box.setText("Ollama lets Conduit run AI models locally on your PC.")
            box.setInformativeText(
                "It can work offline without an AI API key, but local AI models need "
                "a reasonably capable PC and use RAM/VRAM while running."
            )
            install = box.addButton("Install Ollama", QMessageBox.AcceptRole)
            cancel = box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is install:
                ok, message = environment_service.start_ollama_installer()
                if ok:
                    QMessageBox.information(
                        self,
                        "Ollama Installer Started",
                        message + "\n\nWhen installation finishes, click OLLAMA again.",
                    )
                else:
                    QMessageBox.critical(self, "Ollama Install Failed", message)
            return

        installed = _installed_ollama_models()
        entries = ollama_catalog(installed)

        # The two beginner-friendly recommendations must always be shown when
        # absent, even if future curated-catalog contents change.
        required = {
            "qwen2.5vl:7b": "Vision • Desktop • Images",
            "qwen2.5-coder:7b": "Coding • Lightweight",
        }
        present = {str(x.get("name", "")).casefold() for x in entries}
        for name, description in required.items():
            if name.casefold() not in present:
                entries.append({
                    "name": name,
                    "installed": False,
                    "description": description,
                })

        dialog = OllamaModelDialog(entries, current_model="", parent=self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected_entry:
            return

        entry = dialog.selected_entry
        model = str(entry.get("name") or "")
        if not bool(entry.get("installed")):
            answer = QMessageBox.question(
                self,
                "Install Ollama Model",
                f"{model} is not installed.\n\n"
                f"Download this model now?\n\n"
                f"Conduit will open Command Prompt and run:\nollama pull {model}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                ok, message = environment_service.start_model_download(model)
                if ok:
                    QMessageBox.information(
                        self,
                        "Model Download Started",
                        message + "\n\nThe download runs separately. "
                        "When it finishes, choose OLLAMA again and select the model.",
                    )
                else:
                    QMessageBox.critical(self, "Model Download Failed", message)
            return

        self.selected = ("ollama", model)
        self.accept()


def launch_conduit(*, project_root: Path, version: str = "3.1.0") -> int:
    if QApplication.instance() is None:
        try:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Conduit")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)

    chooser = ProviderStartupDialog()
    if chooser.exec() != QDialog.Accepted or not chooser.selected:
        return 0

    provider, model = chooser.selected
    return run_gui(
        provider=provider,
        model=model,
        project_root=project_root,
        no_memory=False,
        version=version,
    )
