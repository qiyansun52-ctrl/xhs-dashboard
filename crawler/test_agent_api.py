import asyncio
import unittest

from fastapi import HTTPException

import ai_api
from agent.events import AgentEventBus
from agent.orchestrator import AgentOrchestrator
from agent.planning import PlanEngine
from agent.run_store import AgentRunStore
from agent.skills.content_research import ContentResearchSkill
from agent.tool_invoker import ToolInvoker


class AgentApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        async def fake_research(request):
            await asyncio.sleep(0)
            return {
                "question": request["question"],
                "task_type": "material",
                "conclusion": "可以先做英国春天校园方向。",
                "recommendations": [],
                "cited_sources": [],
                "related_sources": [],
                "general_advice": [],
                "material_references": [],
                "team_history_references": [],
                "sparse": False,
                "evidence_quality": "strong",
            }

        self.original_enabled = getattr(ai_api, "AGENT_RUNTIME_ENABLED", True)
        self.original_store = getattr(ai_api, "agent_run_store", None)
        self.original_events = getattr(ai_api, "agent_event_bus", None)
        self.original_invoker = getattr(ai_api, "agent_tool_invoker", None)
        self.original_orchestrator = getattr(ai_api, "agent_orchestrator", None)

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

        ai_api.AGENT_RUNTIME_ENABLED = True
        ai_api.agent_run_store = store
        ai_api.agent_event_bus = events
        ai_api.agent_tool_invoker = invoker
        ai_api.agent_orchestrator = orchestrator

    def tearDown(self):
        ai_api.AGENT_RUNTIME_ENABLED = self.original_enabled
        ai_api.agent_run_store = self.original_store
        ai_api.agent_event_bus = self.original_events
        ai_api.agent_tool_invoker = self.original_invoker
        ai_api.agent_orchestrator = self.original_orchestrator

    async def test_create_agent_run_and_fetch_snapshot(self):
        created = await ai_api.create_agent_run(ai_api.CreateAgentRunReq(message="找英国春天标题素材"))
        run_id = created["run"]["id"]

        await ai_api.agent_orchestrator.wait_for_run(run_id)
        snapshot = await ai_api.get_agent_run(run_id)

        self.assertEqual(created["run"]["status"], "planning")
        self.assertEqual(snapshot["run"]["status"], "completed")
        self.assertEqual([step["step_type"] for step in snapshot["steps"]], ["plan", "tool_call", "answer"])

    async def test_agent_events_endpoint_returns_sse_response(self):
        created = await ai_api.create_agent_run(ai_api.CreateAgentRunReq(message="找英国春天标题素材"))
        run_id = created["run"]["id"]

        response = await ai_api.stream_agent_run_events(run_id)

        self.assertEqual(response.media_type, "text/event-stream")
        self.assertEqual(ai_api.agent_event_bus.get_history(run_id)[0]["event"], "run.created")

    async def test_create_agent_run_respects_runtime_flag(self):
        ai_api.AGENT_RUNTIME_ENABLED = False

        with self.assertRaises(HTTPException) as ctx:
            await ai_api.create_agent_run(ai_api.CreateAgentRunReq(message="找英国春天标题素材"))

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_agent_review_action_endpoints_create_list_and_review(self):
        created = await ai_api.create_agent_run(ai_api.CreateAgentRunReq(message="帮我写一组英国春天标题"))
        run_id = created["run"]["id"]

        action_resp = await ai_api.create_agent_review_action(ai_api.CreateAgentReviewActionReq(
            run_id=run_id,
            action_type="save_draft",
            payload={"title": "英国春天标题包", "preview": "5 个标题草稿"},
            rationale="Agent 生成草稿后需要人工确认再落库。",
            evidence_score=0.76,
        ))
        list_resp = await ai_api.list_agent_review_actions(status="pending")
        reviewed_resp = await ai_api.reject_agent_review_action(
            action_resp["action"]["id"],
            ai_api.ReviewAgentActionReq(reason="不适合团队调性"),
        )

        self.assertTrue(action_resp["ok"])
        self.assertEqual(list_resp["actions"][0]["id"], action_resp["action"]["id"])
        self.assertEqual(reviewed_resp["action"]["status"], "rejected")
        self.assertEqual(reviewed_resp["action"]["review_reason"], "不适合团队调性")


if __name__ == "__main__":
    unittest.main()
