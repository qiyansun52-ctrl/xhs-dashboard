import test from "node:test";
import assert from "node:assert/strict";

import {
  designTokens,
  createGlassCardStyle,
  createPrimaryButtonStyle,
} from "./components/designSystem.js";

test("design system exposes production visual tokens", () => {
  assert.equal(designTokens.color.brand, "#FF2442");
  assert.match(designTokens.color.pageBackground, /linear-gradient/);
  assert.equal(designTokens.radius.card, 12);
  assert.equal(designTokens.motion.cardHover, "200ms ease");
});

test("glass card helper returns the spec card surface", () => {
  const style = createGlassCardStyle({ interactive: true });

  assert.equal(style.background, "rgba(255,255,255,0.03)");
  assert.equal(style.border, "1px solid rgba(255,255,255,0.07)");
  assert.equal(style.borderRadius, 12);
  assert.equal(style.transition, "border-color 200ms ease, transform 200ms ease, box-shadow 200ms ease");
});

test("primary button helper uses brand gradient and glow", () => {
  const style = createPrimaryButtonStyle();

  assert.match(style.background, /linear-gradient/);
  assert.equal(style.boxShadow, "0 2px 8px rgba(255,36,66,0.35)");
  assert.equal(style.borderRadius, 8);
});
