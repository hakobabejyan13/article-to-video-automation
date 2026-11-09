// Draws one scene from its layout. Entrances are springs; bullets appear one by one,
// on their voiceover line when the counts match. Data scenes (big_number, bar_chart,
// price_cards) put the icon beside the headline and draw their items with DataView.
import * as Lucide from 'lucide-react';
import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {INLINE_ICON, INLINE_ICON_GAP, type SceneLayout} from '../layout';
import {COLORS, FADE_FRAMES, MARGIN_X} from '../theme';
import type {SceneProps} from '../types';
import {DataView} from './DataViews';
import {Enter, Lines} from './parts';

const pascal = (name: string) =>
  name
    .split('-')
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join('');

const iconFor = (name?: string): React.FC<{size?: number; color?: string; strokeWidth?: number}> | null => {
  if (!name) {
    return null;
  }
  const lib = Lucide as unknown as Record<string, unknown>;
  const icon = (lib.icons as Record<string, unknown>)[pascal(name)] ?? lib[pascal(name)];
  return (icon as React.FC) ?? null; // unknown names draw no icon
};

const bulletStart = (scene: SceneProps, i: number, n: number): number => {
  if (scene.lineStarts.length === n) {
    return Math.max(6, scene.lineStarts[i]);
  }
  const stagger = Math.min(45, Math.floor((scene.durationInFrames * 0.6) / Math.max(1, n)));
  return 12 + i * stagger;
};

export const SceneView: React.FC<{scene: SceneProps; layout: SceneLayout}> = ({scene, layout}) => {
  const frame = useCurrentFrame();
  const fade = interpolate(
    frame,
    [0, FADE_FRAMES, Math.max(FADE_FRAMES + 1, scene.durationInFrames - FADE_FRAMES), scene.durationInFrames],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const Icon = iconFor(scene.visual.icon);
  const center = layout.align === 'center';
  const panel = layout.kind === 'disclosure';

  return (
    <AbsoluteFill style={{opacity: fade}}>
      <AbsoluteFill
        style={{
          padding: `110px ${MARGIN_X}px 170px`,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: center ? 'center' : 'flex-start',
          gap: 28,
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: center ? 'center' : 'flex-start',
            gap: 28,
            ...(panel
              ? {padding: '56px 80px', borderRadius: 32, background: COLORS.panel, border: `3px solid ${COLORS.panelBorder}`}
              : {}),
          }}
        >
          {Icon && !layout.data ? (
            <Enter delay={0}>
              <Icon size={layout.kind === 'quote' ? 110 : 92} color={COLORS.accent} strokeWidth={1.75} />
            </Enter>
          ) : null}
          {layout.data && (Icon || layout.headline) ? (
            <div style={{display: 'flex', alignItems: 'center', gap: INLINE_ICON_GAP}}>
              {Icon ? (
                <Enter delay={0}>
                  <Icon size={INLINE_ICON} color={COLORS.accent} strokeWidth={1.75} />
                </Enter>
              ) : null}
              {layout.headline ? (
                <Enter delay={4}>
                  <Lines f={layout.headline} color={COLORS.text} weight={700} align="left" />
                </Enter>
              ) : null}
            </div>
          ) : null}
          {layout.headline && !layout.data ? (
            <Enter delay={4}>
              <Lines f={layout.headline} color={COLORS.text} weight={700} align={layout.align} />
            </Enter>
          ) : null}
          {layout.quotes.map((q, i) => (
            <Enter key={`q${i}`} delay={8 + i * 6}>
              <Lines f={q} color={COLORS.text} weight={600} align={layout.align} />
            </Enter>
          ))}
          {layout.subs.map((s, i) => (
            <Enter key={`s${i}`} delay={12 + i * 6}>
              <Lines f={s} color={COLORS.sub} weight={400} align={layout.align} />
            </Enter>
          ))}
          {layout.bullets.map((b, i) => (
            <Enter key={`b${i}`} delay={bulletStart(scene, i, layout.bullets.length)} style={{display: 'flex', alignItems: 'flex-start', gap: 34}}>
              <div
                style={{
                  flex: '0 0 76px',
                  height: 76,
                  borderRadius: 38,
                  background: COLORS.accent,
                  color: COLORS.bgFrom,
                  fontSize: 40,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginTop: Math.max(0, (b.fontSize * b.lineHeight - 76) / 2),
                }}
              >
                {i + 1}
              </div>
              <Lines f={b} color={COLORS.text} weight={500} align="left" />
            </Enter>
          ))}
          {layout.data ? <DataView scene={scene} data={layout.data} /> : null}
        </div>
      </AbsoluteFill>
      {layout.tag ? (
        <div
          style={{
            position: 'absolute',
            left: MARGIN_X,
            bottom: 64,
            padding: '10px 26px',
            borderRadius: 999,
            border: `2px solid ${COLORS.muted}`,
            color: COLORS.sub,
            background: 'rgba(11, 18, 32, 0.6)',
          }}
          data-testid="source-tag"
        >
          <Lines f={layout.tag} color={COLORS.sub} weight={500} align="left" />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
