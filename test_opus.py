import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions
from claude_agent_sdk.types import AssistantMessage

async def main():
    log = open("C:/MY_PROJECTS/agent-team-v15/test_opus_log.txt", "w")
    log.write("Testing Opus 4.6 via SDK...\n")
    log.flush()

    options = ClaudeAgentOptions(
        model="claude-opus-4-6",
        max_turns=1,
        permission_mode="bypassPermissions",
    )

    try:
        async for msg in query(prompt="Say OK", options=options):
            if isinstance(msg, AssistantMessage):
                for block in getattr(msg, "content", []):
                    if hasattr(block, "text"):
                        log.write(f"Response: {block.text}\n")
    except Exception as e:
        log.write(f"ERROR: {type(e).__name__}: {e}\n")

    log.write("Done.\n")
    log.close()

asyncio.run(main())
