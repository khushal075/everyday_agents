"""
14_mcp_agent.py

Discover and call a tool provided by a separate MCP server.

Use the battery reading to recommend the robot's next action.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

class Agent:
    """
    Uses a remote tool result to make a local decision.
    """

    async def run(self, robot_id: str) -> str:
        """
        Discover the battery tool, call it and interpret its result.
        :param robot_id:
        :return:
        """
        server_file = Path(__file__).with_name("14_robot_mcp_server.py")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(server_file)],
        )

        # Start the server using the same env as the agent
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                available = await session.list_tools()
                names = {tool.name for tool in available.tools}
                print(f"Discovered tools:", ", ".join(sorted(names)))

                if "check_battery" not in names:
                    return "cannot decide: the battery tool is unavailable"

                result = await session.call_tool(
                    "check_battery",
                    arguments={"robot_id": robot_id},
                )

                messages = [
                    block.text for block in result.content
                    if isinstance(block, TextContent)
                ]

                if result.isError:
                    detail = " ".join(messages) or "No details returned."
                    return f"Cannot decide: battery check failed. {detail}"

                if len(messages) != 1:
                    return f"Cannot decide: Expect one battery reading."

                try:
                    battery = int(messages[0])
                except ValueError:
                    return "Cannot decide: the battery reading is not an integer."

                if not 0 <= battery <= 100:
                    return "Cannot decide: the battery reading is not between 0 and 100."

                print(f"Battery: {battery}%")
                return "Recharge before moving." if battery < 20 else "Ready to move."


def main():
    """
    Read the robot ID and run the agent.
    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--robot", default="robot-1")
    args = parser.parse_args()

    decision = asyncio.run(Agent().run(args.robot))
    print("Decision:", decision)


if __name__ == "__main__":
    main()
