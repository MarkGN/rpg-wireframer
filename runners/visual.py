"""
runners/visual.py — Pygame visual layer for the Wireframer RPG engine.

Renders:
  • Room map image (assets/maps/<room>.png / .jpg)
  • NPC sprites (assets/sprites/<npc>.png / .jpg) arranged in the room
  • Dialogue box with word-wrapped story text
  • Portrait (assets/portraits/<npc>.png) swappable via Ink tags
  • Action menu rendered as clickable / keyboard-selectable items

Ink tag handling:
  • # portrait <filename>   — swap active portrait image
  • # music <filename>      — play looping background music
  • # audio <filename>      — play one-shot sound effect

Config (optional config.ini next to this file):
  [display]
  width = 1280
  height = 720
  fps = 60
  font = Arial
  font_size = 18

  [colours]
  background = 255,255,255
  text = 0,0,0
  dialogue_bg = 220,220,220
  dialogue_border = 80,80,80
  action_highlight = 180,210,255
  action_normal = 240,240,240
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Optional

import pygame

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

RUNNER_DIR = Path(__file__).resolve().parent
ROOT_DIR   = RUNNER_DIR.parent
ASSETS_DIR = ROOT_DIR / "assets"
MAPS_DIR   = ASSETS_DIR / "maps"
SPRITES_DIR = ASSETS_DIR / "sprites"
PORTRAITS_DIR = ASSETS_DIR / "portraits"
AUDIO_DIR  = ASSETS_DIR / "audio"

sys.path.insert(0, str(RUNNER_DIR))
from engine import World  # noqa: E402


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["display"] = {
        "width": "1280",
        "height": "720",
        "fps": "60",
        "font": "Arial",
        "font_size": "18",
    }
    cfg["colours"] = {
        "background": "255,255,255",
        "text": "0,0,0",
        "dialogue_bg": "220,220,220",
        "dialogue_border": "80,80,80",
        "action_highlight": "180,210,255",
        "action_normal": "240,240,240",
    }
    config_path = RUNNER_DIR / "config.ini"
    if config_path.exists():
        cfg.read(config_path)
    return cfg


def _colour(cfg: configparser.ConfigParser, section: str, key: str) -> tuple:
    raw = cfg[section][key]
    return tuple(int(v.strip()) for v in raw.split(","))


# ---------------------------------------------------------------------------
# Asset loaders (return None gracefully if the file is missing)
# ---------------------------------------------------------------------------

def _find_image(directory: Path, stem: str) -> Optional[Path]:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = directory / (stem + ext)
        if p.exists():
            return p
    return None


def _load_image(directory: Path, stem: str) -> Optional[pygame.Surface]:
    path = _find_image(directory, stem)
    if path is None:
        return None
    try:
        return pygame.image.load(str(path)).convert_alpha()
    except pygame.error:
        return None


def _load_audio(filename: str) -> Optional[Path]:
    """Resolve an audio filename to a path, checking AUDIO_DIR first then raw."""
    candidates = [
        AUDIO_DIR / filename,
        Path(filename),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Text / word-wrap utility
# ---------------------------------------------------------------------------

def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Wrap *text* to fit within *max_width* pixels, respecting newlines."""
    lines: list[str] = []
    for paragraph in text.splitlines():
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            test = current + " " + word
            if font.size(test)[0] <= max_width:
                current = test
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Tag parsing
# ---------------------------------------------------------------------------

def _parse_tags(tags: list[str]) -> dict[str, str]:
    """Extract known Ink tags into a dict: portrait / music / audio."""
    result: dict[str, str] = {}
    for tag in tags:
        tag = tag.strip()
        for key in ("portrait", "music", "audio"):
            if tag.lower().startswith(key + " "):
                result[key] = tag[len(key):].strip()
    return result


# ---------------------------------------------------------------------------
# Layout constants (derived from screen size at runtime)
# ---------------------------------------------------------------------------

class Layout:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h

        # Portrait panel — right 18 % of screen, full height
        self.portrait_w = int(w * 0.18)
        self.portrait_rect = pygame.Rect(w - self.portrait_w, 0, self.portrait_w, h)

        # Map area — everything left of the portrait panel
        self.map_rect = pygame.Rect(0, 0, w - self.portrait_w, h)

        # Dialogue box — bottom 30 % of the map area
        dlg_h = int(h * 0.30)
        self.dialogue_rect = pygame.Rect(0, h - dlg_h, w - self.portrait_w, dlg_h)

        # Action menu — sits just above the dialogue box, 20 % height
        menu_h = int(h * 0.20)
        self.menu_rect = pygame.Rect(0, h - dlg_h - menu_h, w - self.portrait_w, menu_h)

        # Sprites area — centre of map above dialogue / menu
        self.sprite_area = pygame.Rect(
            int((w - self.portrait_w) * 0.15),
            int(h * 0.10),
            int((w - self.portrait_w) * 0.70),
            h - dlg_h - menu_h - int(h * 0.10),
        )


# ---------------------------------------------------------------------------
# Main visual runner
# ---------------------------------------------------------------------------

class VisualRunner:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()

        self.cfg = _load_config()
        W = int(self.cfg["display"]["width"])
        H = int(self.cfg["display"]["height"])
        self.fps = int(self.cfg["display"]["fps"])

        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Wireframer")

        font_name = self.cfg["display"]["font"]
        font_size  = int(self.cfg["display"]["font_size"])
        self.font       = pygame.font.SysFont(font_name, font_size)
        self.font_bold  = pygame.font.SysFont(font_name, font_size, bold=True)
        self.font_large = pygame.font.SysFont(font_name, font_size + 6, bold=True)

        self.bg_colour        = _colour(self.cfg, "colours", "background")
        self.text_colour      = _colour(self.cfg, "colours", "text")
        self.dlg_bg_colour    = _colour(self.cfg, "colours", "dialogue_bg")
        self.dlg_border_colour = _colour(self.cfg, "colours", "dialogue_border")
        self.action_hl_colour = _colour(self.cfg, "colours", "action_highlight")
        self.action_nm_colour = _colour(self.cfg, "colours", "action_normal")

        self.layout = Layout(W, H)
        self.clock  = pygame.time.Clock()

        # Engine
        self.world = World()
        self.world.load_world()

        # State
        self.actions: list[tuple[str, str]] = []
        self.selected_index: int = 0
        self.current_portrait: Optional[pygame.Surface] = None
        self.current_map_img:  Optional[pygame.Surface] = None
        self.sprite_cache:     dict[str, Optional[pygame.Surface]] = {}
        self.current_room_id:  Optional[str] = None
        self.current_music:    Optional[str] = None
        self.dialogue_text:    str = ""

        self._refresh_room()

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_room(self):
        room_id = self.world.current_room
        if room_id != self.current_room_id:
            self.current_room_id = room_id
            self.current_map_img = _load_image(MAPS_DIR, room_id)
            self.sprite_cache = {}

        # Default portrait: player.png when not in dialogue
        if self.world.dialogue_partner is None:
            self._set_portrait("player")
        else:
            self._set_portrait(self.world.dialogue_partner)

        self.actions = self.world.get_actions()
        if self.selected_index >= len(self.actions):
            self.selected_index = 0

        self.dialogue_text = self.world.last_story_text or ""
        self._handle_story_tags()

    def _set_portrait(self, stem: str):
        img = _load_image(PORTRAITS_DIR, stem)
        self.current_portrait = img

    def _handle_story_tags(self):
        """Process any pending Ink tags on the current story."""
        story = self.world.story
        if story is None:
            return
        raw_tags: list[str] = []
        try:
            raw_tags = story.current_tags or []
        except Exception:
            return
        tags = _parse_tags(raw_tags)
        if "portrait" in tags:
            self._set_portrait(tags["portrait"])
        if "music" in tags:
            self._play_music(tags["music"])
        if "audio" in tags:
            self._play_sfx(tags["audio"])

    def _play_music(self, filename: str):
        if filename == self.current_music:
            return
        path = _load_audio(filename)
        if path is None:
            return
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play(-1)  # loop
            self.current_music = filename
        except pygame.error:
            pass

    def _play_sfx(self, filename: str):
        path = _load_audio(filename)
        if path is None:
            return
        try:
            sfx = pygame.mixer.Sound(str(path))
            sfx.play()
        except pygame.error:
            pass

    def _get_sprite(self, npc_id: str) -> Optional[pygame.Surface]:
        if npc_id not in self.sprite_cache:
            self.sprite_cache[npc_id] = _load_image(SPRITES_DIR, npc_id)
        return self.sprite_cache[npc_id]

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_map(self):
        """Draw the room background image or a plain rectangle."""
        area = self.layout.map_rect
        if self.current_map_img:
            scaled = pygame.transform.smoothscale(self.current_map_img, (area.width, area.height))
            self.screen.blit(scaled, area.topleft)
        else:
            pygame.draw.rect(self.screen, (200, 200, 210), area)
            label = self.font_large.render(self.world.current_room, True, self.text_colour)
            self.screen.blit(label, (area.x + 20, area.y + 20))

    def _draw_sprites(self):
        npcs = self.world.npcs_in_room()
        if not npcs:
            return
        area = self.layout.sprite_area
        sprite_target_h = min(area.height, 200)
        spacing = area.width // (len(npcs) + 1)
        for i, npc_id in enumerate(npcs):
            sprite = self._get_sprite(npc_id)
            cx = area.x + spacing * (i + 1)
            cy = area.centery
            if sprite:
                ratio = sprite_target_h / sprite.get_height()
                sw = int(sprite.get_width() * ratio)
                scaled = pygame.transform.smoothscale(sprite, (sw, sprite_target_h))
                self.screen.blit(scaled, (cx - sw // 2, cy - sprite_target_h // 2))
            else:
                # Placeholder silhouette
                r = pygame.Rect(cx - 24, cy - 48, 48, 96)
                pygame.draw.rect(self.screen, (150, 150, 170), r, border_radius=8)
                name = self.world.npcs.get(npc_id, {}).get("name", npc_id)
                lbl = self.font.render(name, True, self.text_colour)
                self.screen.blit(lbl, (cx - lbl.get_width() // 2, cy + 52))

    def _draw_dialogue(self):
        rect = self.layout.dialogue_rect
        pygame.draw.rect(self.screen, self.dlg_bg_colour, rect)
        pygame.draw.rect(self.screen, self.dlg_border_colour, rect, 2)
        pad = 12
        max_w = rect.width - pad * 2
        lines = _wrap_text(self.dialogue_text, self.font, max_w)
        line_h = self.font.get_linesize()
        y = rect.y + pad
        for line in lines:
            if y + line_h > rect.bottom - pad:
                break
            surf = self.font.render(line, True, self.text_colour)
            self.screen.blit(surf, (rect.x + pad, y))
            y += line_h

    def _draw_menu(self):
        rect = self.layout.menu_rect
        pygame.draw.rect(self.screen, self.bg_colour, rect)
        pygame.draw.rect(self.screen, self.dlg_border_colour, rect, 1)
        pad = 8
        item_h = self.font.get_linesize() + 6
        y = rect.y + pad
        for i, (action, target) in enumerate(self.actions):
            label = f"{action}: {target}" if target else action
            item_rect = pygame.Rect(rect.x + pad, y, rect.width - pad * 2, item_h)
            colour = self.action_hl_colour if i == self.selected_index else self.action_nm_colour
            pygame.draw.rect(self.screen, colour, item_rect, border_radius=4)
            txt = self.font.render(f"[{i+1}] {label}", True, self.text_colour)
            self.screen.blit(txt, (item_rect.x + 6, item_rect.y + 3))
            y += item_h + 4
            if y + item_h > rect.bottom - pad:
                break

    def _draw_portrait(self):
        rect = self.layout.portrait_rect
        pygame.draw.rect(self.screen, self.dlg_bg_colour, rect)
        pygame.draw.rect(self.screen, self.dlg_border_colour, rect, 2)
        if self.current_portrait:
            # Scale to fill width, preserve aspect, centre vertically
            pw = rect.width - 8
            ph = int(self.current_portrait.get_height() * pw / self.current_portrait.get_width())
            scaled = pygame.transform.smoothscale(self.current_portrait, (pw, ph))
            x = rect.x + 4
            y = rect.y + (rect.height - ph) // 2
            self.screen.blit(scaled, (x, y))

    def _draw(self):
        self.screen.fill(self.bg_colour)
        self._draw_map()
        self._draw_sprites()
        self._draw_portrait()
        self._draw_dialogue()
        self._draw_menu()
        pygame.display.flip()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _select_action(self, index: int):
        if not self.actions:
            return
        index = max(0, min(index, len(self.actions) - 1))
        action, target = self.actions[index]
        self.world.handle_action(action, target)
        self._refresh_room()

    def _handle_events(self) -> bool:
        """Return False to quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                if event.key == pygame.K_UP:
                    self.selected_index = (self.selected_index - 1) % max(1, len(self.actions))
                elif event.key == pygame.K_DOWN:
                    self.selected_index = (self.selected_index + 1) % max(1, len(self.actions))
                elif event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                    self._select_action(self.selected_index)
                else:
                    # Number keys 1–9
                    num = event.key - pygame.K_1
                    if 0 <= num < len(self.actions):
                        self.selected_index = num
                        self._select_action(num)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                menu_rect = self.layout.menu_rect
                pad = 8
                item_h = self.font.get_linesize() + 6
                y = menu_rect.y + pad
                for i in range(len(self.actions)):
                    item_rect = pygame.Rect(menu_rect.x + pad, y, menu_rect.width - pad * 2, item_h)
                    if item_rect.collidepoint(mx, my):
                        self.selected_index = i
                        self._select_action(i)
                        break
                    y += item_h + 4
                    if y + item_h > menu_rect.bottom - pad:
                        break

            if event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                menu_rect = self.layout.menu_rect
                pad = 8
                item_h = self.font.get_linesize() + 6
                y = menu_rect.y + pad
                for i in range(len(self.actions)):
                    item_rect = pygame.Rect(menu_rect.x + pad, y, menu_rect.width - pad * 2, item_h)
                    if item_rect.collidepoint(mx, my):
                        self.selected_index = i
                        break
                    y += item_h + 4
                    if y + item_h > menu_rect.bottom - pad:
                        break

        return True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        running = True
        while running:
            running = self._handle_events()
            self._draw()
            self.clock.tick(self.fps)
        pygame.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    runner = VisualRunner()
    runner.run()