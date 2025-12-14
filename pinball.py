"""
Neon Space Arcade Pinball (Python / tkinter)

Why tkinter?
- It's included with most Python installs (no pip installs needed)
- Canvas is perfect for simple 2D arcade rendering

This is a small, kid-friendly pinball with:
- Simple gravity + velocity physics
- Circle/segment collision detection
- Two flippers (left/right arrows), launch (space/down)
- Score + lives, start + game-over overlays
- Bumper flash + screen shake

Run:
  python3 pinball.py
"""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from dataclasses import dataclass


# ----------------------------
# Math helpers (2D vectors)
# ----------------------------

@dataclass
class Vec:
    x: float
    y: float

    def __add__(self, o: "Vec") -> "Vec":
        return Vec(self.x + o.x, self.y + o.y)

    def __sub__(self, o: "Vec") -> "Vec":
        return Vec(self.x - o.x, self.y - o.y)

    def __mul__(self, s: float) -> "Vec":
        return Vec(self.x * s, self.y * s)

    def dot(self, o: "Vec") -> float:
        return self.x * o.x + self.y * o.y

    def mag(self) -> float:
        return math.hypot(self.x, self.y)

    def norm(self) -> "Vec":
        m = self.mag()
        return Vec(0.0, 0.0) if m == 0 else Vec(self.x / m, self.y / m)


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


# ----------------------------
# Game objects
# ----------------------------

class Ball:
    def __init__(self, radius: float = 10.0) -> None:
        self.r = radius
        self.pos = Vec(0.0, 0.0)
        self.vel = Vec(0.0, 0.0)
        self.active = False

    def reset_in_lane(self, w: float, h: float) -> None:
        # Plunger lane (right side)
        self.pos = Vec(w - 20, h - 100)
        self.vel = Vec(0.0, 0.0)
        self.active = True

    def launch(self, w: float) -> None:
        # Allow launch any time the ball is in the right lane
        if self.active and self.pos.x > w - 60:
            self.vel = Vec(self.vel.x, -20 - random.random() * 5)


class Bumper:
    def __init__(self, x: float, y: float, r: float, color: str) -> None:
        self.pos = Vec(x, y)
        self.r = r
        self.base_color = color
        self.flash_frames = 0

    def hit(self) -> None:
        self.flash_frames = 10


class Segment:
    def __init__(self, x1: float, y1: float, x2: float, y2: float, kind: str = "wall") -> None:
        self.p1 = Vec(x1, y1)
        self.p2 = Vec(x2, y2)
        self.kind = kind  # wall / slingshot / lane / rail
        dx = self.p2.x - self.p1.x
        dy = self.p2.y - self.p1.y
        ln = math.hypot(dx, dy) or 1.0
        # Left-hand normal
        self.normal = Vec(-dy / ln, dx / ln)


class Flipper:
    """
    Flipper is a rotating segment (pivot -> tip), rendered as a thin rectangle.
    We keep angles mirrored so kids visually understand left/right symmetry.
    """

    def __init__(self, x: float, y: float, length: float, side: str, start_ang: float, max_ang: float) -> None:
        self.pivot = Vec(x, y)
        self.length = length
        self.side = side  # "left" or "right"

        # Left rests at +30deg, flips to -45deg.
        # Right rests at 180-30=150deg, flips to 180+45=225deg.
        self.rest_angle = start_ang if side == "left" else math.pi - start_ang
        self.flip_angle = -max_ang if side == "left" else math.pi + max_ang

        self.angle = self.rest_angle
        self.target = self.rest_angle
        self.width = 10.0

    def set_pressed(self, pressed: bool) -> None:
        self.target = self.flip_angle if pressed else self.rest_angle

    def update(self, speed: float) -> None:
        # Smooth move towards target (simple, stable, kid-friendly feel)
        self.angle += (self.target - self.angle) * speed

    def tip(self) -> Vec:
        return Vec(
            self.pivot.x + math.cos(self.angle) * self.length,
            self.pivot.y + math.sin(self.angle) * self.length,
        )


# ----------------------------
# Pinball Game (tkinter)
# ----------------------------

class PinballGame:
    # Logical resolution (physics units)
    W = 400.0
    H = 700.0

    # Neon palette
    BG = "#120a2e"
    BALL = "#ffffff"
    FLIPPER = "#00f3ff"
    BUMPER = "#ff00ff"
    SLING = "#ccff00"
    WALL = "#8a2be2"
    TARGET = "#ffaa00"

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Neon Space Arcade Pinball (Python)")
        self.root.configure(bg="#05030f")

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg=self.BG)
        self.canvas.pack(fill="both", expand=True)

        # UI state
        self.state = "start"  # start, playing, gameover
        self.score = 0
        self.lives = 3

        # Physics constants (per frame)
        self.gravity = 0.25
        self.friction = 0.99
        self.wall_bounce = 0.6
        self.flipper_speed = 0.25

        # Screen shake
        self.shake_frames = 0

        # Scaling / viewport
        self.scale = 1.0
        self.offx = 0.0
        self.offy = 0.0

        # Game objects
        self.ball = Ball(radius=10.0)
        self.segs: list[Segment] = []
        self.bumpers: list[Bumper] = []
        self.left = Flipper(110, self.H - 60, 70, "left", start_ang=math.pi / 6, max_ang=math.pi / 4)
        self.right = Flipper(260, self.H - 60, 70, "right", start_ang=math.pi / 6, max_ang=math.pi / 4)

        # Input state
        self.left_down = False
        self.right_down = False

        # Scoring cooldown (prevents wall score spam while resting)
        self.frame = 0
        self.last_wall_score_frame = -999

        # Overlay button area (in screen pixels)
        self.btn_rect = (0, 0, 0, 0)

        self._build_table()
        self._bind_events()

        self._on_resize()
        self._tick()

    # ----------------------------
    # Setup
    # ----------------------------

    def _bind_events(self) -> None:
        self.root.bind("<KeyPress>", self._on_key_down)
        self.root.bind("<KeyRelease>", self._on_key_up)
        self.canvas.bind("<Button-1>", self._on_click)
        self.root.bind("<Configure>", lambda _e: self._on_resize())

    def _build_table(self) -> None:
        self.segs.clear()
        self.bumpers.clear()

        # Table boundaries + plunger lane:
        # Left wall must reach bottom to prevent corner escapes.
        self.segs.append(Segment(0, 0, 0, self.H, "wall"))
        self.segs.append(Segment(0, 100, 100, 0, "wall"))                 # top-left arch
        self.segs.append(Segment(100, 0, self.W - 40, 0, "wall"))          # top

        # Right edge and plunger lane guides
        self.segs.append(Segment(self.W, 0, self.W, self.H, "wall"))       # far right edge
        self.segs.append(Segment(self.W - 40, 140, self.W - 40, self.H - 40, "lane"))  # lane divider
        self.segs.append(Segment(self.W - 40, self.H - 40, self.W, self.H - 40, "lane"))  # lane floor
        self.segs.append(Segment(self.W, 140, self.W - 40, 0, "wall"))     # top-right deflector

        # Drain guides (slanted walls)
        self.segs.append(Segment(0, self.H - 200, 110, self.H - 60, "wall"))
        self.segs.append(Segment(self.W - 40, self.H - 200, self.W - 150, self.H - 60, "wall"))

        # Bottom rails: keep ball in pit; leave drain gap between flippers.
        drain_left = 165
        drain_right = 235
        self.segs.append(Segment(0, self.H, drain_left, self.H, "rail"))
        self.segs.append(Segment(drain_right, self.H, self.W, self.H, "rail"))

        # Slingshots (triangles)
        # Left
        self.segs.append(Segment(40, self.H - 180, 40, self.H - 120, "slingshot"))
        self.segs.append(Segment(40, self.H - 120, 90, self.H - 150, "slingshot"))
        self.segs.append(Segment(90, self.H - 150, 40, self.H - 180, "slingshot"))
        # Right
        self.segs.append(Segment(self.W - 80, self.H - 180, self.W - 80, self.H - 120, "slingshot"))
        self.segs.append(Segment(self.W - 80, self.H - 120, self.W - 130, self.H - 150, "slingshot"))
        self.segs.append(Segment(self.W - 130, self.H - 150, self.W - 80, self.H - 180, "slingshot"))

        # Bumpers (triangle at top-center)
        self.bumpers.append(Bumper(self.W / 2, 150, 25, self.BUMPER))
        self.bumpers.append(Bumper(self.W / 2 - 60, 220, 25, self.BUMPER))
        self.bumpers.append(Bumper(self.W / 2 + 60, 220, 25, self.BUMPER))

    # ----------------------------
    # Coordinate transforms
    # ----------------------------

    def _on_resize(self) -> None:
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.scale = min(cw / self.W, ch / self.H)
        self.offx = (cw - self.W * self.scale) / 2
        self.offy = (ch - self.H * self.scale) / 2

    def _sx(self, x: float) -> float:
        return self.offx + x * self.scale

    def _sy(self, y: float) -> float:
        return self.offy + y * self.scale

    def _sw(self, w: float) -> float:
        return w * self.scale

    # ----------------------------
    # Input
    # ----------------------------

    def _on_key_down(self, e: tk.Event) -> None:
        if self.state != "playing":
            return
        if e.keysym == "Left":
            self.left_down = True
        elif e.keysym == "Right":
            self.right_down = True
        elif e.keysym in ("Down", "space"):
            self.ball.launch(self.W)

    def _on_key_up(self, e: tk.Event) -> None:
        if e.keysym == "Left":
            self.left_down = False
        elif e.keysym == "Right":
            self.right_down = False

    def _on_click(self, e: tk.Event) -> None:
        x, y = e.x, e.y
        x1, y1, x2, y2 = self.btn_rect
        if x1 <= x <= x2 and y1 <= y <= y2:
            self._start_game()

    # ----------------------------
    # Game state transitions
    # ----------------------------

    def _start_game(self) -> None:
        self.state = "playing"
        self.score = 0
        self.lives = 3
        self.shake_frames = 0
        self.left_down = False
        self.right_down = False
        self.left.set_pressed(False)
        self.right.set_pressed(False)
        self._build_table()
        self.ball.reset_in_lane(self.W, self.H)

    def _game_over(self) -> None:
        self.state = "gameover"

    def _lose_ball(self) -> None:
        self.lives -= 1
        self._shake(12)
        if self.lives <= 0:
            self._game_over()
        else:
            self.ball.reset_in_lane(self.W, self.H)

    # ----------------------------
    # Effects + scoring
    # ----------------------------

    def _shake(self, frames: int) -> None:
        self.shake_frames = max(self.shake_frames, frames)

    def _add_score(self, pts: int) -> None:
        self.score += pts

    # ----------------------------
    # Physics loop
    # ----------------------------

    def _tick(self) -> None:
        # Fixed timestep-ish at ~60 fps using tkinter "after"
        self.frame += 1

        if self.state == "playing":
            # Update flippers
            self.left.set_pressed(self.left_down)
            self.right.set_pressed(self.right_down)
            self.left.update(self.flipper_speed)
            self.right.update(self.flipper_speed)

            # Update ball
            self._step_ball()

        self._render()
        self.root.after(16, self._tick)

    def _step_ball(self) -> None:
        if not self.ball.active:
            return

        # Apply gravity + integrate
        self.ball.vel = Vec(self.ball.vel.x * self.friction, (self.ball.vel.y + self.gravity) * self.friction)
        self.ball.pos = self.ball.pos + self.ball.vel

        # Top clamp (prevents rare tunneling into upper corners)
        if self.ball.pos.y < self.ball.r:
            self.ball.pos = Vec(self.ball.pos.x, self.ball.r)
            self.ball.vel = Vec(self.ball.vel.x, abs(self.ball.vel.y) * self.wall_bounce)

        # Lose ball if it falls out bottom
        if self.ball.pos.y > self.H + 50:
            self._lose_ball()
            return

        # Collisions (2 passes reduce tunneling for simple engines)
        self._resolve_collisions()
        self._resolve_collisions()

    def _resolve_collisions(self) -> None:
        # Ball vs segments
        for seg in self.segs:
            self._collide_ball_segment(seg)

        # Ball vs bumpers
        for b in self.bumpers:
            self._collide_ball_bumper(b)

        # Ball vs flippers (as segments)
        self._collide_ball_flipper(self.left)
        self._collide_ball_flipper(self.right)

        # Simple left/right safety clamp (should be redundant with walls, but keeps it robust)
        if self.ball.pos.x < self.ball.r:
            self.ball.pos = Vec(self.ball.r, self.ball.pos.y)
            self.ball.vel = Vec(-self.ball.vel.x * self.wall_bounce, self.ball.vel.y)
        if self.ball.pos.x > self.W - self.ball.r:
            self.ball.pos = Vec(self.W - self.ball.r, self.ball.pos.y)
            self.ball.vel = Vec(-self.ball.vel.x * self.wall_bounce, self.ball.vel.y)

    def _collide_ball_segment(self, seg: Segment) -> None:
        # Closest point on segment to ball center
        p1, p2 = seg.p1, seg.p2
        v = p2 - p1
        vv = v.dot(v) or 1.0
        t = ((self.ball.pos - p1).dot(v)) / vv
        t = clamp(t, 0.0, 1.0)
        closest = p1 + v * t
        d = self.ball.pos - closest
        dist = d.mag()

        if dist < self.ball.r:
            # Push out along normal
            n = d.norm()
            if dist == 0:
                n = seg.normal
            overlap = self.ball.r - dist
            self.ball.pos = self.ball.pos + n * overlap

            # Reflect velocity: v' = v - (1+e)(v·n)n
            dot = self.ball.vel.dot(n)
            restitution = 1.5 if seg.kind == "slingshot" else self.wall_bounce
            self.ball.vel = Vec(
                self.ball.vel.x - (1 + restitution) * dot * n.x,
                self.ball.vel.y - (1 + restitution) * dot * n.y,
            )

            # Scoring + effects
            if seg.kind == "slingshot":
                self._add_score(10)
                self._shake(4)
            else:
                # Wall = 10 points, but throttle so it doesn't spam
                if self.frame - self.last_wall_score_frame > 6:
                    self._add_score(10)
                    self.last_wall_score_frame = self.frame

    def _collide_ball_bumper(self, b: Bumper) -> None:
        d = self.ball.pos - b.pos
        dist = d.mag()
        if dist < self.ball.r + b.r:
            n = d.norm() if dist != 0 else Vec(0, -1)
            overlap = (self.ball.r + b.r) - dist
            self.ball.pos = self.ball.pos + n * overlap

            # Give it a strong bounce
            speed = max(5.0, self.ball.vel.mag()) * 1.2
            self.ball.vel = n * speed

            b.hit()
            self._add_score(100)
            self._shake(8)

    def _collide_ball_flipper(self, f: Flipper) -> None:
        # Flipper as a segment
        p1 = f.pivot
        p2 = f.tip()
        v = p2 - p1
        vv = v.dot(v) or 1.0
        t = ((self.ball.pos - p1).dot(v)) / vv
        t = clamp(t, 0.0, 1.0)
        closest = p1 + v * t
        d = self.ball.pos - closest
        dist = d.mag()

        flipper_r = 5.0
        if dist < self.ball.r + flipper_r:
            n = d.norm() if dist != 0 else Vec(0, -1)
            overlap = (self.ball.r + flipper_r) - dist
            self.ball.pos = self.ball.pos + n * overlap

            dot = self.ball.vel.dot(n)
            self.ball.vel = Vec(
                self.ball.vel.x - 2 * dot * n.x,
                self.ball.vel.y - 2 * dot * n.y,
            )

            # If flipper is moving upward, add a stronger impulse ("kick")
            moving_up = (f.side == "left" and f.target < f.angle) or (f.side == "right" and f.target > f.angle)
            if moving_up:
                self.ball.vel = Vec(self.ball.vel.x + (5 if f.side == "left" else -5), self.ball.vel.y - 10)
                self._shake(2)
            else:
                # resting contact friction
                self.ball.vel = Vec(self.ball.vel.x * 0.95, self.ball.vel.y)

    # ----------------------------
    # Rendering
    # ----------------------------

    def _render(self) -> None:
        self.canvas.delete("all")

        # Screen shake (in screen pixels, scaled)
        shake_px = 0.0
        if self.shake_frames > 0:
            shake_px = (self.shake_frames * 0.8)
            self.shake_frames -= 1

        sx = random.uniform(-shake_px, shake_px)
        sy = random.uniform(-shake_px, shake_px)

        def X(x: float) -> float:
            return self._sx(x) + sx

        def Y(y: float) -> float:
            return self._sy(y) + sy

        # Background (full canvas already bg, but draw a vignette-ish border)
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        self.canvas.create_rectangle(0, 0, cw, ch, fill="#05030f", outline="")
        self.canvas.create_rectangle(self._sx(0), self._sy(0), self._sx(self.W), self._sy(self.H), fill=self.BG, outline="")

        # Neon grid (subtle)
        grid_color = "#2a1655"
        step = 40
        for gx in range(0, int(self.W) + 1, step):
            self.canvas.create_line(X(gx), Y(0), X(gx), Y(self.H), fill=grid_color, width=1)
        for gy in range(0, int(self.H) + 1, step):
            self.canvas.create_line(X(0), Y(gy), X(self.W), Y(gy), fill=grid_color, width=1)

        # Segments (walls)
        for seg in self.segs:
            color = self.SLING if seg.kind == "slingshot" else self.WALL
            w = self._sw(5)
            # Faux glow: draw thick darker line under, then normal
            self.canvas.create_line(X(seg.p1.x), Y(seg.p1.y), X(seg.p2.x), Y(seg.p2.y), fill=color, width=w + self._sw(6), capstyle="round")
            self.canvas.create_line(X(seg.p1.x), Y(seg.p1.y), X(seg.p2.x), Y(seg.p2.y), fill=color, width=w, capstyle="round")

        # Bumpers
        for b in self.bumpers:
            col = "#ffffff" if b.flash_frames > 0 else b.base_color
            if b.flash_frames > 0:
                b.flash_frames -= 1
            r = self._sw(b.r)
            self.canvas.create_oval(X(b.pos.x - b.r), Y(b.pos.y - b.r), X(b.pos.x + b.r), Y(b.pos.y + b.r),
                                    fill=col, outline="")
            # inner ring
            self.canvas.create_oval(X(b.pos.x - b.r * 0.6), Y(b.pos.y - b.r * 0.6),
                                    X(b.pos.x + b.r * 0.6), Y(b.pos.y + b.r * 0.6),
                                    outline="#330033", width=self._sw(2))

        # Flippers
        self._draw_flipper(self.left, X, Y)
        self._draw_flipper(self.right, X, Y)

        # Ball
        if self.ball.active:
            r = self.ball.r
            # glow underlay
            self.canvas.create_oval(X(self.ball.pos.x - r * 1.6), Y(self.ball.pos.y - r * 1.6),
                                    X(self.ball.pos.x + r * 1.6), Y(self.ball.pos.y + r * 1.6),
                                    fill="#cccccc", outline="")
            self.canvas.create_oval(X(self.ball.pos.x - r), Y(self.ball.pos.y - r),
                                    X(self.ball.pos.x + r), Y(self.ball.pos.y + r),
                                    fill=self.BALL, outline="")

        # HUD (score + lives)
        self.canvas.create_text(self._sx(self.W / 2), self._sy(40), text=str(self.score),
                                fill=self.TARGET, font=("Arial Black", int(self._sw(28))))
        self.canvas.create_text(self._sx(self.W / 2), self._sy(78), text=f"BALLS: {self.lives}",
                                fill=self.FLIPPER, font=("Verdana", int(self._sw(14)), "bold"))

        # Overlay
        if self.state in ("start", "gameover"):
            self._draw_overlay()

    def _draw_flipper(self, f: Flipper, X, Y) -> None:
        # Draw a thin rectangle rotated by f.angle.
        # Axis direction
        ax = math.cos(f.angle)
        ay = math.sin(f.angle)
        # Perpendicular direction
        px = -ay
        py = ax

        half_w = f.width / 2
        p1 = f.pivot
        p2 = f.tip()

        # Rectangle corners around segment p1->p2
        a = Vec(p1.x + px * half_w, p1.y + py * half_w)
        b = Vec(p1.x - px * half_w, p1.y - py * half_w)
        c = Vec(p2.x - px * half_w, p2.y - py * half_w)
        d = Vec(p2.x + px * half_w, p2.y + py * half_w)

        pts = [X(a.x), Y(a.y), X(b.x), Y(b.y), X(c.x), Y(c.y), X(d.x), Y(d.y)]

        # Faux glow by drawing a bigger polygon under
        self.canvas.create_polygon(pts, fill=self.FLIPPER, outline="")

    def _draw_overlay(self) -> None:
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()

        # Dim screen
        self.canvas.create_rectangle(0, 0, cw, ch, fill="#000000", outline="")

        title = "SPACE PINBALL" if self.state == "start" else "GAME OVER"
        btn = "PLAY" if self.state == "start" else "PLAY AGAIN"

        self.canvas.create_text(cw / 2, ch / 2 - 80, text=title, fill=self.BUMPER,
                                font=("Arial Black", int(min(cw, ch) * 0.06)))
        self.canvas.create_text(cw / 2, ch / 2 - 35,
                                text="Left/Right arrows = flippers   Space/Down = launch",
                                fill="#dddddd", font=("Verdana", 12))

        # Button
        bw, bh = 240, 60
        x1 = cw / 2 - bw / 2
        y1 = ch / 2 + 20
        x2 = cw / 2 + bw / 2
        y2 = ch / 2 + 20 + bh
        self.btn_rect = (x1, y1, x2, y2)

        self.canvas.create_rectangle(x1, y1, x2, y2, fill="#222222", outline=self.FLIPPER, width=3)
        self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=btn, fill="#ffffff",
                                font=("Arial Black", 22))

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    PinballGame().run()


