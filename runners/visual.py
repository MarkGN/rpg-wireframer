from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
import pygame

from .action import Action, render_action
from .context_independent_actions import (
    get_context_independent_actions,
    handle_context_independent_action,
)
from .contexts.dialogue import Dialogue
from .contexts.encounter import Encounter
from .contexts.explore import Explore
from .contexts.shop import Shop
from .presentation import format_inventory, format_quest_log
from .world import World

WIDTH = 800
HEIGHT = 600
IMAGE_HEIGHT = 390
ACTION_HEIGHT = 35
VISIBLE_ACTIONS = 6
BACKGROUND = (24, 27, 32)
PANEL = (38, 42, 50)
TEXT = (238, 240, 244)
MUTED = (173, 180, 192)
ACCENT = (76, 137, 214)
WARNING = (220, 150, 72)


class VisualRunner:
    def __init__(self, game_dir: Path):
        pygame.init()
        pygame.display.set_caption("Wireframer")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 20)
        self.small_font = pygame.font.SysFont("arial", 16)
        self.title_font = pygame.font.SysFont("arial", 24, bold=True)
        self.game_dir = game_dir
        self.world = World(game_dir, custom_external_input=self.custom_input)
        self.action_offset = 0
        self.overlay: str | None = None
        self.running = True
        self.previous_speaker: str | None = None
        self.speaker_side = "left"

    def run(self) -> None:
        while self.running:
            events = pygame.event.get()
            self.handle_events(events)
            if self.running:
                self.draw()
                pygame.display.flip()
                self.clock.tick(60)
        pygame.quit()

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
                return
            if self.overlay is not None:
                if event.type in {pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN}:
                    self.overlay = None
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.running = False
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.click(event.pos)

    def click(self, position: tuple[int, int]) -> None:
        x, y = position
        if y < IMAGE_HEIGHT:
            return

        context_actions = self.current_actions()
        independent = get_context_independent_actions(self.world)
        all_actions: list[tuple[str, Any]] = [
            ("independent", action) for action in independent
        ] + [("context", action) for action in context_actions]
        max_offset = max(0, len(all_actions) - VISIBLE_ACTIONS)
        if max_offset and y >= HEIGHT - 40:
            if x >= WIDTH // 2 and self.action_offset < max_offset:
                self.action_offset += 1
            elif x < WIDTH // 2 and self.action_offset > 0:
                self.action_offset -= 1
            return
        page_start = self.action_offset
        page = all_actions[page_start : page_start + VISIBLE_ACTIONS]
        button_index = (y - IMAGE_HEIGHT) // ACTION_HEIGHT
        if not 0 <= button_index < len(page):
            return

        kind, action = page[button_index]
        if kind == "independent":
            if handle_context_independent_action(self.world, action["id"]):
                self.running = False
            elif action["id"] in {"inventory", "quest_log"}:
                self.overlay = action["id"]
        else:
            self.world.handle_action(action)
        self.action_offset = 0

    def current_actions(self) -> list[Action]:
        return self.world.get_actions()

    def all_action_labels(self) -> list[str]:
        independent = get_context_independent_actions(self.world)
        labels = [entry["label"] for entry in independent]
        labels.extend(render_action(self.world, action) for action in self.current_actions())
        return labels

    def draw(self) -> None:
        self.screen.fill(BACKGROUND)
        if self.overlay is not None:
            self.draw_overlay(self.overlay)
            return

        context = self.world.get_context()
        if isinstance(context, Explore):
            self.draw_explore()
        elif isinstance(context, Dialogue):
            self.draw_dialogue(context)
        elif isinstance(context, Shop):
            self.draw_shop(context)
        elif isinstance(context, Encounter):
            self.draw_encounter()
        self.draw_actions()

    def draw_explore(self) -> None:
        self.draw_room()
        objects = self.world.world_state["rooms"][self.world.current_room].get(
            "objects", []
        )
        for index, object_id in enumerate(objects):
            if object_id in self.world.world_state["objects"]:
                x = 20 + (index % 6) * 125
                y = 30 + (index // 6) * 145
                self.draw_asset(
                    self.game_dir / "assets" / "sprites" / f"{object_id}.png",
                    pygame.Rect(x, y, 96, 96),
                )

    def draw_dialogue(self, context: Dialogue) -> None:
        self.draw_room()
        speaker = context.current_speaker
        if speaker != self.previous_speaker:
            if self.previous_speaker is not None:
                self.speaker_side = "right" if self.speaker_side == "left" else "left"
            self.previous_speaker = speaker
        portrait_path = self.portrait_path(speaker)
        x = 35 if self.speaker_side == "left" else WIDTH - 195
        portrait = self.draw_asset(portrait_path, pygame.Rect(x, 20, 160, 190))
        if self.speaker_side == "right" and portrait is not None:
            mirrored = pygame.transform.flip(portrait, True, False)
            self.screen.blit(mirrored, (x, 20))
        text_box = pygame.Rect(24, 220, WIDTH - 48, 150)
        pygame.draw.rect(self.screen, PANEL, text_box)
        self.draw_wrapped(context.last_text, text_box.inflate(-20, -16))

    def draw_shop(self, context: Shop) -> None:
        self.screen.fill(PANEL, (0, 0, WIDTH, IMAGE_HEIGHT))
        npc = self.world.world_state["objects"].get(context.npc, {})
        self.draw_asset(
            self.portrait_path(context.npc, npc),
            pygame.Rect(28, 30, 170, 220),
        )
        self.draw_text(
            npc.get("name", context.npc),
            (220, 35),
            self.title_font,
        )
        self.draw_wrapped(context.line, pygame.Rect(220, 75, 540, 70))
        for index, item_id in enumerate(context.inventory):
            item = self.world.world_state["items"].get(item_id, {})
            self.draw_text(
                f"{item.get('name', item_id)}  {item.get('price', '?')}",
                (220, 150 + index * 32),
                self.font,
            )

    def draw_encounter(self) -> None:
        self.screen.fill(PANEL, (0, 0, WIDTH, IMAGE_HEIGHT))
        self.draw_text("You are in an encounter!", (28, 35), self.title_font)

    def draw_room(self) -> None:
        room_path = self.game_dir / "assets" / "maps" / (self.world.current_room + ".png")
        self.draw_asset(room_path, pygame.Rect(0, 0, WIDTH, IMAGE_HEIGHT))
        room = self.world.display_room()
        self.screen.fill((0, 0, 0, 120), (0, IMAGE_HEIGHT - 58, WIDTH, 58))
        self.draw_text(room["name"], (16, IMAGE_HEIGHT - 48), self.title_font)

    def draw_actions(self) -> None:
        labels = self.all_action_labels()
        if not labels:
            return
        max_offset = max(0, len(labels) - VISIBLE_ACTIONS)
        self.action_offset = min(self.action_offset, max_offset)
        page = labels[self.action_offset : self.action_offset + VISIBLE_ACTIONS]
        for index, label in enumerate(page):
            rect = pygame.Rect(
                12, IMAGE_HEIGHT + index * ACTION_HEIGHT + 2, WIDTH - 24, 30
            )
            pygame.draw.rect(self.screen, PANEL, rect)
            self.draw_text(f"{index + 1}. {label}", (25, rect.y + 5), self.small_font)
        if max_offset:
            if self.action_offset > 0:
                self.draw_text("< previous actions", (WIDTH - 190, HEIGHT - 30), self.small_font)
            if self.action_offset < max_offset:
                self.draw_text("next actions >", (WIDTH - 150, HEIGHT - 30), self.small_font)

    def draw_overlay(self, kind: str) -> None:
        self.screen.fill(PANEL)
        title = "Inventory" if kind == "inventory" else "Quest log"
        self.draw_text(title, (24, 24), self.title_font)
        lines = format_inventory(self.world) if kind == "inventory" else format_quest_log(self.world)
        for index, line in enumerate(lines):
            self.draw_wrapped(str(line), pygame.Rect(28, 75 + index * 30, WIDTH - 56, 50))
        self.draw_text("Click or press any key to return", (24, HEIGHT - 35), self.small_font)

    def draw_asset(self, path: Path, rect: pygame.Rect) -> pygame.Surface | None:
        try:
            image = pygame.image.load(path).convert_alpha()
            image = pygame.transform.smoothscale(image, rect.size)
            self.screen.blit(image, rect)
            return image
        except (FileNotFoundError, pygame.error):
            pygame.draw.rect(self.screen, (65, 48, 32), rect)
            self.draw_wrapped(
                f"warning: {path.relative_to(self.game_dir)} not found",
                rect.inflate(-8, -8),
                self.small_font,
                WARNING,
            )
            return None

    def portrait_path(self, speaker: str, metadata: dict[str, Any] | None = None) -> Path:
        metadata = metadata or self.world.world_state["objects"].get(speaker, {})
        portrait = metadata.get("portrait")
        if portrait:
            candidate = self.game_dir / "assets" / "portraits" / str(portrait)
            if candidate.suffix == "":
                candidate = candidate.with_suffix(".png")
            return candidate
        candidates = [
            self.game_dir / "assets" / "portraits" / f"{speaker}.png",
            self.game_dir / "assets" / "portraits" / f"{str(speaker).lower()}.png",
        ]
        return candidates[0] if candidates[0].exists() else candidates[1]

    def custom_input(self, prompt: str) -> str:
        value = ""
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    return ""
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        return value
                    if event.key == pygame.K_BACKSPACE:
                        value = value[:-1]
                    elif event.unicode:
                        value += event.unicode
            self.screen.fill(BACKGROUND)
            self.draw_text(prompt, (24, 210), self.font)
            self.draw_text(value + "_", (24, 260), self.font)
            pygame.display.flip()
            self.clock.tick(60)
        return ""

    def draw_text(
        self,
        text: str,
        position: tuple[int, int],
        font: pygame.font.Font | None = None,
        color: tuple[int, int, int] = TEXT,
    ) -> None:
        self.screen.blit((font or self.font).render(text, True, color), position)

    def draw_wrapped(
        self,
        text: str,
        rect: pygame.Rect,
        font: pygame.font.Font | None = None,
        color: tuple[int, int, int] = TEXT,
    ) -> None:
        font = font or self.font
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if font.size(candidate)[0] <= rect.width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        for index, line in enumerate(lines):
            y = rect.y + index * (font.get_linesize() + 2)
            if y + font.get_height() > rect.bottom:
                break
            self.draw_text(line, (rect.x, y), font, color)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m runners.visual GAME")
    VisualRunner(Path(sys.argv[1])).run()


if __name__ == "__main__":
    main()
