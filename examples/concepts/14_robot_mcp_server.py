"""
14_robot_mcp_server.py

Expose a simulated battery sensor as an MCP tool.

The agent launches this file as a subprocess
"""

from mcp.server.fastmcp import FastMCP

server = FastMCP("robot-tools")

BATTERY_LEVELS: dict[str, int] = {
    "robot-1": 15,
    "robot-2": 80
}

@server.tool()
def check_battery(robot_id: str) -> str:
    """
    Return the robot's battery percentage as text.
    :param robot_id:
    :return:
    """
    if robot_id not in BATTERY_LEVELS:
        raise ValueError(f"Unknown robot: {robot_id}")

    return str(BATTERY_LEVELS[robot_id])

if __name__ == "__main__":
    # Keep stdout available for MCP messages.
    server.run(transport="stdio")
