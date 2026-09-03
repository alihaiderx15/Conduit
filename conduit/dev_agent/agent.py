
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from conduit.core.errors import ProviderError
from conduit.core.models import ChatMessage, Role
from conduit.core.progress_watchdog import ProgressStalledError, run_with_progress_watchdog
from conduit.code_helper import code_service
from .models import ProjectPlan
from .service import DeveloperAgentError, DeveloperProjectService, dev_service


class DeveloperAgent:
    """Specialist multi-file developer orchestrator.

    It deliberately reuses the active GeneralPCAgent provider, model, event bus,
    provider recovery and memory-bearing conversation session. Mechanical file,
    execution and dependency operations stay in DeveloperProjectService.
    """

    def __init__(self, general_agent, *, service: DeveloperProjectService | None = None) -> None:
        self.general_agent = general_agent
        self.service = service or dev_service

    async def emit(self, stage: str, **payload) -> None:
        events = getattr(self.general_agent, "events", None)
        if events is not None and hasattr(events, "emit"):
            await events.emit(
                "dev.stage",
                source="DeveloperAgent",
                payload={"stage": stage, **payload},
            )

    async def model_text(self, prompt: str, *, timeout: float | None = None) -> str:
        """Provider call with no total deadline; stop only when progress stalls."""

        async def on_check(snapshot):
            await self.emit(
                "provider_watchdog",
                elapsed_seconds=round(snapshot.elapsed_seconds, 1),
                seconds_since_progress=round(snapshot.seconds_since_progress, 1),
                progress_units=snapshot.progress_units,
                detail=snapshot.detail,
                missed_checks=snapshot.missed_checks,
            )

        async def request_once(heartbeat):
            provider = self.general_agent.loop.provider
            if hasattr(provider, "specialist_chat_with_progress"):
                return await provider.specialist_chat_with_progress(
                    [ChatMessage(Role.USER, prompt)],
                    model=self.general_agent.loop.model,
                    on_progress=heartbeat,
                )
            heartbeat(0, "request dispatched")
            response = await provider.specialist_chat(
                [ChatMessage(Role.USER, prompt)], model=self.general_agent.loop.model
            )
            heartbeat(max(1, len(response.text)), "response complete")
            return response

        try:
            response = await run_with_progress_watchdog(
                request_once,
                check_interval=60.0,
                initial_missed_checks=2,
                active_missed_checks=1,
                on_check=on_check,
            )
        except ProgressStalledError as exc:
            raise DeveloperAgentError(
                str(exc) + " Please try again or switch to a faster coding model."
            ) from exc
        except ProviderError as exc:
            recovered = await self.general_agent.recover_provider_error(exc)
            if not recovered:
                raise DeveloperAgentError(
                    "The AI provider became unavailable and the developer task was cancelled."
                ) from exc
            try:
                response = await run_with_progress_watchdog(
                    request_once,
                    check_interval=60.0,
                    initial_missed_checks=2,
                    active_missed_checks=1,
                    on_check=on_check,
                )
            except ProgressStalledError as stalled:
                raise DeveloperAgentError(
                    str(stalled) + " Please try again or switch to a faster coding model."
                ) from stalled
        return response.text.strip()

    @staticmethod
    def strip_json_fence(text: str) -> str:
        value = str(text or "").strip()
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
        return value.strip()

    async def plan_project(self, request: str) -> ProjectPlan:
        await self.emit("planning")
        prompt = (
            "You are Conduit's project architect. Plan a practical MULTI-FILE software project. "
            "Return STRICT JSON only with this shape:\n"
            '{"name":"safe-project-name","language":"python|javascript|typescript|html|other",'
            '"framework":"","description":"","entry_point":"",'
            '"dependencies":["..."],"test_strategy":"",'
            '"files":[{"path":"relative/path","purpose":"what belongs here"}]}\n\n'
            "Keep the project reasonably small and coherent (normally 3-12 files). "
            "Never use absolute paths or '..'. Include README.md and useful tests when appropriate. "
            f"\nUSER REQUEST:\n{request}"
        )
        raw = self.strip_json_fence(await self.model_text(prompt))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DeveloperAgentError(f"The model returned an invalid project plan: {exc}") from exc

        files = data.get("files", [])
        if not isinstance(files, list) or not files:
            raise DeveloperAgentError("The project plan did not contain any files.")
        clean_files: list[dict[str, str]] = []
        for row in files[:30]:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "").strip()
            purpose = str(row.get("purpose") or "").strip()
            self.service._safe_relpath(path)
            clean_files.append({"path": path, "purpose": purpose})
        if not clean_files:
            raise DeveloperAgentError("The project plan did not contain valid relative file paths.")

        plan = ProjectPlan(
            name=self.service.safe_project_name(str(data.get("name") or request)),
            language=str(data.get("language") or "python").strip(),
            framework=str(data.get("framework") or "").strip(),
            description=str(data.get("description") or "").strip(),
            entry_point=str(data.get("entry_point") or "").strip(),
            files=clean_files,
            dependencies=[str(x) for x in data.get("dependencies", []) if str(x).strip()][:50],
            test_strategy=str(data.get("test_strategy") or "").strip(),
        )
        await self.emit("planned", name=plan.name, files=len(plan.files), language=plan.language)
        return plan

    async def generate_project_files(self, request: str, plan: ProjectPlan) -> dict[str, str]:
        await self.emit(
            "generating_files",
            files=len(plan.files),
            watchdog_interval_seconds=60,
        )
        file_spec = "\n".join(
            f"- {item['path']}: {item['purpose']}" for item in plan.files
        )
        prompt = (
            "Generate the COMPLETE contents for every file in this MULTI-FILE project. "
            "Return STRICT JSON only. The response must be one JSON object whose keys are EXACT "
            "relative paths and whose values are complete file contents. No Markdown fences, no commentary. "
            "All imports/references between files must be internally consistent. Do not leave TODOs, "
            "placeholders, pseudocode, or omitted sections. Prefer minimal dependencies.\n\n"
            f"PROJECT REQUEST:\n{request}\n\n"
            f"PROJECT PLAN:\n{json.dumps(plan.as_dict(), ensure_ascii=False)}\n\n"
            f"FILES TO GENERATE:\n{file_spec}"
        )
        raw = self.strip_json_fence(await self.model_text(prompt, timeout=None))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DeveloperAgentError(f"The model returned invalid project-file JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise DeveloperAgentError("Project generation did not return a file map.")

        expected = [item["path"] for item in plan.files]
        result: dict[str, str] = {}
        for path in expected:
            if path not in data:
                raise DeveloperAgentError(f"Generated project is missing planned file: {path}")
            content = data[path]
            if not isinstance(content, str) or not content.strip():
                raise DeveloperAgentError(f"Generated project file is empty: {path}")
            self.service._safe_relpath(path)
            result[path] = code_service.strip_code_fences(content) if path.lower().endswith(
                (".py",".js",".jsx",".ts",".tsx",".java",".c",".cpp",".cs",".go",".rs")
            ) else content
        await self.emit("files_generated", files=len(result))
        return result

    async def create_project(self, request: str, *, path: str = "", base_dir: str = ""):
        plan = await self.plan_project(request)
        files = await self.generate_project_files(request, plan)
        root = self.service.create_from_files(
            project_name=plan.name,
            files=files,
            plan=plan,
            path=path,
            base_dir=base_dir or None,
        )
        await self.emit("created", root=str(root), files=len(files))
        return root, plan

    async def analyze_error(self, *, user_request: str, result) -> str:
        project_text = self.service.read_project_text()
        prompt = (
            "Analyze this MULTI-FILE project failure. Explain the likely root cause and identify the "
            "specific project files that should change. Be concise but technically precise.\n\n"
            f"USER GOAL:\n{user_request}\n\n"
            f"ERROR CATEGORY: {result.category.value}\nCOMMAND: {list(result.command)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n\nPROJECT FILES:\n{project_text}"
        )
        return await self.model_text(prompt)

    async def generate_patch(self, *, user_request: str, result=None) -> dict[str, str]:
        await self.emit("generating_patch", timeout_seconds=360)
        project_text = self.service.read_project_text()
        failure = ""
        if result is not None:
            failure = (
                f"\nERROR CATEGORY: {result.category.value}\nCOMMAND: {list(result.command)}"
                f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
            )
        prompt = (
            "Modify this MULTI-FILE project to satisfy the user request and/or repair the shown failure. "
            "Return STRICT JSON only: an object mapping ONLY files that need changes to their COMPLETE "
            "replacement contents. Do not return unchanged files. Do not use absolute paths or '..'. "
            "Preserve working behavior outside the requested change.\n\n"
            f"USER REQUEST:\n{user_request}\n{failure}\nPROJECT:\n{project_text}"
        )
        raw = self.strip_json_fence(await self.model_text(prompt, timeout=None))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DeveloperAgentError(f"The model returned invalid patch JSON: {exc}") from exc
        if not isinstance(data, dict) or not data:
            raise DeveloperAgentError("The model did not return any project file patches.")
        patches: dict[str, str] = {}
        for path, content in data.items():
            self.service._safe_relpath(path)
            if not isinstance(content, str) or not content.strip():
                raise DeveloperAgentError(f"Patch content is empty for {path}")
            patches[path] = code_service.strip_code_fences(content) if str(path).lower().endswith(
                (".py",".js",".jsx",".ts",".tsx",".java",".c",".cpp",".cs",".go",".rs")
            ) else content
        return patches

    async def patch_project(self, request: str):
        await self.emit("patching")
        patches = await self.generate_patch(user_request=request)
        written = self.service.patch_files(patches)
        await self.emit("patched", files=[str(x) for x in written])
        return written

    async def repair_until_working(self, request: str, *, max_attempts: int = 3):
        await self.emit("repair_start", max_attempts=max_attempts)
        result = self.service.run_tests()
        if not result.success and result.category.value in {"entry_point_missing","build_tool_missing"}:
            result = self.service.run_project()
        elif result.success:
            run_result = self.service.run_project()
            if not run_result.success:
                result = run_result
            else:
                return run_result, 0

        original_result = result
        for attempt in range(1, max_attempts + 1):
            await self.emit(
                "repair_attempt",
                attempt=attempt,
                category=result.category.value,
            )
            patches = await self.generate_patch(user_request=request, result=result)
            self.service.patch_files(patches)
            test_result = self.service.run_tests()
            if test_result.success:
                run_result = self.service.run_project()
                if run_result.success or run_result.category.value == "timeout":
                    await self.emit("repair_succeeded", attempt=attempt)
                    return run_result if run_result.success else test_result, attempt
                result = run_result
            else:
                result = test_result

        await self.emit("repair_failed", category=result.category.value)
        return result or original_result, max_attempts
