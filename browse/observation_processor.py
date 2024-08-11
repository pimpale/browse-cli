import asyncio
from dataclasses import dataclass
from playwright.async_api import Page, CDPSession, ViewportSize
from typing import Any, Optional, TypedDict
import re
from .utils import (
    AccessibilityTree,
    AccessibilityTreeNode,
    BrowserConfig,
    BrowserInfo,
    DOMNode,
)
import time


async def fetch_browser_info(
    page: Page,
    client: CDPSession,
) -> BrowserInfo:
    viewport_size = page.viewport_size
    assert viewport_size is not None, "Viewport size is None"

    # extract domtree
    tree = await client.send(
        "DOMSnapshot.captureSnapshot",
        {
            "computedStyles": [],
            "includeDOMRects": True,
            "includePaintOrder": True,
        },
    )

    # calibrate the bounds, in some cases, the bounds are scaled somehow
    bounds = tree["documents"][0]["layout"]["bounds"]
    b = bounds[0]
    n = b[2] / viewport_size["width"]
    bounds = [[x / n for x in bound] for bound in bounds]
    tree["documents"][0]["layout"]["bounds"] = bounds

    # extract browser info
    win_top_bound = await page.evaluate("window.pageYOffset")
    win_left_bound = await page.evaluate("window.pageXOffset")
    win_width = await page.evaluate("window.screen.width")
    win_height = await page.evaluate("window.screen.height")
    win_right_bound = win_left_bound + win_width
    win_lower_bound = win_top_bound + win_height
    device_pixel_ratio = await page.evaluate("window.devicePixelRatio")
    assert device_pixel_ratio == 1.0, "devicePixelRatio is not 1.0"

    config: BrowserConfig = {
        "win_top_bound": win_top_bound,
        "win_left_bound": win_left_bound,
        "win_width": win_width,
        "win_height": win_height,
        "win_right_bound": win_right_bound,
        "win_lower_bound": win_lower_bound,
        "device_pixel_ratio": device_pixel_ratio,
    }

    # assert len(tree['documents']) == 1, "More than one document in the DOM tree"
    info: BrowserInfo = {"DOMTree": tree, "config": config}

    return info


async def get_bounding_client_rect(
    client: CDPSession, backend_node_id: int
) -> list[float] | None:
    try:
        remote_object = await client.send(
            "DOM.resolveNode", {"backendNodeId": backend_node_id}
        )
        remote_object_id = remote_object["object"]["objectId"]
        response = await client.send(
            "Runtime.callFunctionOn",
            {
                "objectId": remote_object_id,
                "functionDeclaration": """
                    function() {
                        if (this.nodeType == 3) {
                            var range = document.createRange();
                            range.selectNode(this);
                            var rect = range.getBoundingClientRect().toJSON();
                            range.detach();
                            return rect;
                        } else {
                            return this.getBoundingClientRect().toJSON();
                        }
                    }
                """,
                "returnByValue": True,
            },
        )
        x = response["result"]["value"]["x"]
        y = response["result"]["value"]["y"]
        width = response["result"]["value"]["width"]
        height = response["result"]["value"]["height"]

        union_bound = [x, y, width, height]

        return union_bound
    except Exception:
        return None


async def get_bounding_client_rect2(
    client: CDPSession, backend_node_id: int
) -> list[float] | None:
    try:
        boxmodel = await client.send(
            "DOM.getBoxModel", {"backendNodeId": backend_node_id}
        )
        x = boxmodel["model"]["padding"][0]
        y = boxmodel["model"]["padding"][1]
        width = boxmodel["model"]["width"]
        height = boxmodel["model"]["height"]
        union_bound = [x, y, width, height]
        return union_bound
    except Exception:
        return None


def get_element_in_viewport_ratio(
    elem_left_bound: float,
    elem_top_bound: float,
    width: float,
    height: float,
    config: BrowserConfig,
) -> float:
    elem_right_bound = elem_left_bound + width
    elem_lower_bound = elem_top_bound + height

    win_left_bound = 0
    win_right_bound = config["win_width"]
    win_top_bound = 0
    win_lower_bound = config["win_height"]

    # Compute the overlap in x and y axes
    overlap_width = max(
        0,
        min(elem_right_bound, win_right_bound) - max(elem_left_bound, win_left_bound),
    )
    overlap_height = max(
        0,
        min(elem_lower_bound, win_lower_bound) - max(elem_top_bound, win_top_bound),
    )

    # Compute the overlap area
    ratio = overlap_width * overlap_height / width * height
    return ratio


async def fetch_accessibility_tree(
    client: CDPSession,
) -> AccessibilityTree:
    t0 = time.time()
    accessibility_tree: AccessibilityTree = (
        await client.send("Accessibility.getFullAXTree", {})
    )["nodes"]
    print(f"Accessibility.getFullAXTree: {time.time() - t0}")

    # a few nodes are repeated in the accessibility tree
    seen_ids = set()
    _accessibility_tree = []
    for node in accessibility_tree:
        if node["nodeId"] not in seen_ids:
            _accessibility_tree.append(node)
            seen_ids.add(node["nodeId"])
    accessibility_tree = _accessibility_tree

    return accessibility_tree


@dataclass
class ObsNode:
    depth: int
    role: str
    name: str
    properties: list[str]
    backend_id: int | None


IGNORED_ACTREE_PROPERTIES = (
    "focusable",
    "editable",
    "readonly",
    "level",
    "settable",
    "multiline",
    "invalid",
)


async def parse_accessibility_tree(
    browser_info: BrowserInfo,
    accessibility_tree: AccessibilityTree,
    client: CDPSession,
) -> list[ObsNode]:
    """Parse the accessibility tree into a string text"""
    node_id_to_idx: dict[str, int] = {}
    for idx, node in enumerate(accessibility_tree):
        node_id_to_idx[node["nodeId"]] = idx

    async def convert_node(
        depth: int, node: AccessibilityTreeNode
    ) -> tuple[Optional[ObsNode], Optional[list[str]]]:
        maybe_children = node.get("childIds", None)

        role = node["role"]["value"]
        try:
            name = node["name"]["value"]
        except KeyError:
            return None, maybe_children

        properties = []
        for property in node.get("properties", []):
            try:
                if property["name"] in IGNORED_ACTREE_PROPERTIES:
                    continue
                properties.append(f'{property["name"]}: {property["value"]["value"]}')
            except KeyError:
                pass

        maybe_node = ObsNode(
            depth=depth,
            role=role,
            name=name,
            backend_id=node.get("backendDOMNodeId", None),
            properties=properties,
        )

        union_bound = (
            await get_bounding_client_rect(client, node["backendDOMNodeId"])
            if "backendDOMNodeId" in node
            else None
        )
        if union_bound is None:
            return None, maybe_children
        x, y, width, height = union_bound
        if width == 0 or height == 0:
            return None, None
        in_viewport_ratio = get_element_in_viewport_ratio(
            x, y, width, height, browser_info["config"]
        )
        if in_viewport_ratio == 0:
            return None, None

        # empty generic node
        if not name.strip():
            if not properties:
                if role in [
                    "generic",
                    "img",
                    "list",
                    "strong",
                    "paragraph",
                    "banner",
                    "navigation",
                    "Section",
                    "LabelText",
                    "Legend",
                    "listitem",
                    "ListMarker",
                    "superscript",
                ]:
                    maybe_node = None
            elif role in ["listitem"]:
                maybe_node = None

        # don't descend into these nodes
        # * link typically just contains statictext with the link text
        if role in ["link", "heading"]:
            maybe_children = None

        return maybe_node, maybe_children

    async def dfs(idx: int, depth: int) -> list[ObsNode]:
        obs_nodes_info: list[ObsNode] = []

        maybe_node, maybe_children = await convert_node(depth, accessibility_tree[idx])

        if maybe_node is not None:
            obs_nodes_info.append(maybe_node)

        if maybe_children is not None:
            child_depth = depth + 1 if maybe_node is not None else depth
            child_nodes = [
                await dfs(node_id_to_idx[child_node_id], child_depth)
                for child_node_id in maybe_children
                if child_node_id in node_id_to_idx
            ]
            # child_nodes = await asyncio.gather(*child_nodes)
            for child_node in child_nodes:
                obs_nodes_info.extend(child_node)

        return obs_nodes_info

    return await dfs(0, 0)

def obs_nodes_to_str(obs_nodes_info: list[ObsNode]) -> str:
    """Stringify the observation nodes info"""
    tree_str = ""
    depth = 0
    prev_fusable = False
    for i, v in enumerate(obs_nodes_info):

        if v.depth == depth and prev_fusable and v.role in ["StaticText", "link"] and len(v.properties) == 0:
            # add space between fusable nodes if they are not already separated by space
            if tree_str[-1] != " " and v.name[0] != " ":
                tree_str += " "
                
            if v.role == "StaticText":
                tree_str += f"{v.name}"
            else:
                tree_str += f"[{v.name}]({i})"
        else:
            indent_str = "\t" * v.depth

            if v.role == "StaticText":
                tree_str += f"\n{indent_str}{v.name} "
            elif v.role == "link":
                tree_str += f"\n{indent_str}[{v.name}]({i}) "
            else:
                id_str = f"({i}) "
                role_str = f"{v.role}: "
                name_str = f"'{v.name}'"
                property_str = " ".join(v.properties) if v.properties else ""
                tree_str += f"\n{indent_str}{id_str}{role_str}{name_str}{property_str}"
            
            depth = v.depth
            prev_fusable = v.role in ["StaticText", "link"] and len(v.properties) == 0
    
    return tree_str
        


def tree_loaded_successfully(accessibility_tree: AccessibilityTree) -> bool:
    root = next(
        obj for obj in accessibility_tree if obj["role"]["value"] == "RootWebArea"
    )
    # check if has busy attribute
    busy_attr = next((obj for obj in root["properties"] if obj["name"] == "busy"), None)
    return busy_attr is None


async def process(page: Page, client: CDPSession) -> list[ObsNode]:
    browser_info = await fetch_browser_info(page, client)
    while True:
        accessibility_tree = await fetch_accessibility_tree(
            client,
        )

        # check if the tree is loaded successfully
        if tree_loaded_successfully(accessibility_tree):
            break
        else:
            # wait for a while
            await page.wait_for_timeout(100)

    return await parse_accessibility_tree(browser_info, accessibility_tree, client)


async def get_element_center(
    obs_nodes_info: list[ObsNode], element_id: int, client: CDPSession
) -> tuple[float, float]:
    try:
        node_info = obs_nodes_info[element_id]
    except IndexError:
        raise ValueError(f"Element with id {element_id} not found")

    if node_info.backend_id is None:
        raise ValueError("Node backend_id is None")

    node_bound = await get_bounding_client_rect(client, node_info.backend_id)
    if node_bound is None:
        raise ValueError("Node bound is None")
    x, y, width, height = node_bound
    center_x = x + width / 2
    center_y = y + height / 2
    return (
        center_x,
        center_y,
    )
