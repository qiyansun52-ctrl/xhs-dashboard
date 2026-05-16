import asyncio
import unittest

from agent.events import AgentEventBus
from agent.orchestrator import AgentOrchestrator
from agent.planning import PlanEngine
from agent.run_store import AgentRunStore
from agent.skills.content_research import ContentResearchSkill
from agent.tool_invoker import ToolInvoker


class MissingSchemaTable:
    def __init__(self, calls):
        self.calls = calls

    def insert(self, rows):
        self.calls.append(("insert", rows))
        return self

    def update(self, payload):
        self.calls.append(("update", payload))
        return self

    def execute(self):
        raise Exception("Could not find the table 'public.agent_runs' in the schema cache")


class MissingSchemaSupabase:
    def __init__(self):
        self.calls = []

    def table(self, name):
        self.calls.append(("table", name))
        return MissingSchemaTable(self.calls)


class ToolInvocationLookupTable:
    def __init__(self, data, calls):
        self.data = data
        self.calls = calls

    def select(self, value):
        self.calls.append(("select", value))
        return self

    def eq(self, field, value):
        self.calls.append(("eq", field, value))
        return self

    def maybe_single(self):
        self.calls.append(("maybe_single",))
        return self

    def execute(self):
        return type("Response", (), {"data": self.data})()


class ToolInvocationLookupSupabase:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def table(self, name):
        self.calls.append(("table", name))
        return ToolInvocationLookupTable(self.data, self.calls)


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_falls_back_to_memory_when_agent_schema_is_missing(self):
        supabase = MissingSchemaSupabase()
        store = AgentRunStore(supabase)

        run = await store.create_run("找罗格斯申请帖子")
        updated = await store.update_run(run["id"], status="running")
        step = await store.create_step(run["id"], "plan")
        completed_step = await store.complete_step(run["id"], step["id"], output_payload={"intent": "material_research"})
        snapshot = await store.get_run_snapshot(run["id"])

        self.assertEqual(updated["status"], "running")
        self.assertEqual(completed_step["status"], "completed")
        self.assertEqual(snapshot["run"]["id"], run["id"])
        self.assertEqual(snapshot["steps"][0]["output_payload"]["intent"], "material_research")
        self.assertEqual(supabase.calls.count(("table", "agent_runs")), 1)

    async def test_run_completes_and_records_minimum_timeline(self):
        async def fake_research(request):
            await asyncio.sleep(0)
            return {
                "question": request["question"],
                "task_type": "material",
                "conclusion": "可以先参考英国春天校园和樱花方向。",
                "recommendations": [{"text": "优先写春日校园氛围。", "source_ids": []}],
                "cited_sources": [],
                "related_sources": [],
                "general_advice": [],
                "material_references": [],
                "team_history_references": [],
                "sparse": False,
                "evidence_quality": "strong",
            }

        store = AgentRunStore()
        events = AgentEventBus()
        invoker = ToolInvoker(store)
        skill = ContentResearchSkill(fake_research)
        orchestrator = AgentOrchestrator(
            run_store=store,
            event_bus=events,
            tool_invoker=invoker,
            planner=PlanEngine(store),
            skills={skill.name: skill},
        )

        run = await orchestrator.create_run("找英国春天标题素材")
        await orchestrator.wait_for_run(run["id"])

        snapshot = await store.get_run_snapshot(run["id"])

        self.assertEqual(snapshot["run"]["status"], "completed")
        self.assertEqual(snapshot["run"]["final_answer"]["conclusion"], "可以先参考英国春天校园和樱花方向。")
        self.assertEqual([step["step_type"] for step in snapshot["steps"]], ["plan", "tool_call", "answer"])
        self.assertEqual(snapshot["steps"][0]["output_payload"]["skill_chain"][0]["skill_name"], "content_research")
        self.assertEqual(snapshot["steps"][1]["tool_name"], "content_research")
        self.assertEqual(snapshot["steps"][1]["status"], "completed")

        history = events.get_history(run["id"])
        self.assertEqual(history[0]["event"], "run.created")
        self.assertEqual(history[-1]["event"], "run.completed")

    async def test_tool_invoker_reuses_completed_idempotent_result(self):
        store = AgentRunStore()
        invoker = ToolInvoker(store)
        calls = {"count": 0}

        async def fake_tool(payload):
            calls["count"] += 1
            return {"echo": payload["question"]}

        first = await invoker.invoke(
            tool_name="research",
            input_payload={"question": "英国春天"},
            idempotency_key="run-1:step-1",
            fn=fake_tool,
        )
        second = await invoker.invoke(
            tool_name="research",
            input_payload={"question": "英国春天"},
            idempotency_key="run-1:step-1",
            fn=fake_tool,
        )

        self.assertEqual(calls["count"], 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["output"]["echo"], "英国春天")

    async def test_tool_invoker_marks_failed_call_and_allows_retry(self):
        store = AgentRunStore()
        invoker = ToolInvoker(store)
        calls = {"count": 0}

        async def flaky_tool(payload):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary outage")
            return {"echo": payload["question"]}

        with self.assertRaises(RuntimeError):
            await invoker.invoke(
                tool_name="research",
                input_payload={"question": "英国春天"},
                idempotency_key="run-1:step-2",
                fn=flaky_tool,
            )

        failed = await store.get_tool_invocation("run-1:step-2")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["output_payload"]["error"], "temporary outage")

        retried = await invoker.invoke(
            tool_name="research",
            input_payload={"question": "英国春天"},
            idempotency_key="run-1:step-2",
            fn=flaky_tool,
        )

        self.assertEqual(calls["count"], 2)
        self.assertFalse(retried["cached"])
        self.assertEqual(retried["output"]["echo"], "英国春天")

    async def test_tool_invoker_rejects_reused_key_with_different_input(self):
        store = AgentRunStore()
        invoker = ToolInvoker(store)

        async def fake_tool(payload):
            return {"echo": payload["question"]}

        await invoker.invoke(
            tool_name="research",
            input_payload={"question": "英国春天"},
            idempotency_key="run-1:step-3",
            fn=fake_tool,
        )

        with self.assertRaises(RuntimeError):
            await invoker.invoke(
                tool_name="research",
                input_payload={"question": "澳洲春天"},
                idempotency_key="run-1:step-3",
                fn=fake_tool,
            )

    async def test_store_reads_tool_invocation_from_database_when_not_in_memory(self):
        persisted = {
            "idempotency_key": "run-1:step-4",
            "tool_name": "research",
            "input_hash": "hash",
            "output_payload": {"ok": True},
            "status": "completed",
        }
        supabase = ToolInvocationLookupSupabase(persisted)
        store = AgentRunStore(supabase)

        record = await store.get_tool_invocation("run-1:step-4")
        cached = await store.get_tool_invocation("run-1:step-4")

        self.assertEqual(record["output_payload"]["ok"], True)
        self.assertEqual(cached["status"], "completed")
        self.assertEqual(supabase.calls.count(("table", "tool_invocations")), 1)

    async def test_failed_research_marks_run_failed(self):
        async def exploding_research(request):
            raise RuntimeError("boom")

        store = AgentRunStore()
        events = AgentEventBus()
        invoker = ToolInvoker(store)
        skill = ContentResearchSkill(exploding_research)
        orchestrator = AgentOrchestrator(
            run_store=store,
            event_bus=events,
            tool_invoker=invoker,
            planner=PlanEngine(store),
            skills={skill.name: skill},
        )

        run = await orchestrator.create_run("找英国春天标题素材")
        await orchestrator.wait_for_run(run["id"])
        snapshot = await store.get_run_snapshot(run["id"])

        self.assertEqual(snapshot["run"]["status"], "failed")
        self.assertIn("boom", snapshot["run"]["error_message"])
        self.assertEqual(events.get_history(run["id"])[-1]["event"], "run.failed")

    async def test_review_actions_can_be_created_listed_and_rejected(self):
        store = AgentRunStore()
        run = await store.create_run("把这组选题存为草稿")

        action = await store.create_review_action(
            run_id=run["id"],
            action_type="save_draft",
            payload={"title": "英国春日校园选题", "preview": "从校园樱花切入申请季焦虑"},
            rationale="用户要求把 Agent 产出落地为草稿，需人工确认后再写库。",
            evidence_score=0.82,
            duplicate_warning=None,
        )
        pending = await store.list_review_actions(status="pending")
        rejected = await store.review_action(action["id"], status="rejected", review_reason="低质量")
        remaining_pending = await store.list_review_actions(status="pending")

        self.assertEqual(action["status"], "pending")
        self.assertEqual(action["action_type"], "save_draft")
        self.assertEqual(pending[0]["id"], action["id"])
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["review_reason"], "低质量")
        self.assertIsNotNone(rejected["reviewed_at"])
        self.assertEqual(remaining_pending, [])


if __name__ == "__main__":
    unittest.main()
