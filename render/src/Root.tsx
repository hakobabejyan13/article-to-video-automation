import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {Main} from './Main';
import type {VideoProps} from './types';

// Made-up props for the Studio preview only; real runs pass --props.
const sample: VideoProps = {
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 90,
  minFontPx: 36,
  scenes: [
    {
      id: 1,
      from: 0,
      durationInFrames: 90,
      audio: null,
      lineStarts: [0],
      sourceTag: 'Source: Example guide',
      visual: {type: 'card', variant: 'title', icon: 'info'},
      onScreen: [
        {role: 'headline', text: 'Example headline'},
        {role: 'sub', text: 'A made-up sub line for the preview'},
      ],
    },
  ],
};

// The video is exactly as long as the scenes added up (PLAN.md section 4 (a)).
export const checkProps = (props: VideoProps): void => {
  let next = 0;
  for (const s of props.scenes) {
    if (s.from !== next || s.durationInFrames < 1) {
      throw new Error(`Scene ${s.id}: starts at frame ${s.from}, expected ${next} (length ${s.durationInFrames})`);
    }
    next += s.durationInFrames;
  }
  if (next !== props.durationInFrames) {
    throw new Error(`The scenes add up to ${next} frames but durationInFrames is ${props.durationInFrames}`);
  }
};

const calculateMetadata: CalculateMetadataFunction<VideoProps> = ({props}) => {
  checkProps(props);
  return {durationInFrames: props.durationInFrames, fps: props.fps, width: props.width, height: props.height};
};

export const Root: React.FC = () => (
  <Composition
    id="Main"
    component={Main}
    width={1920}
    height={1080}
    fps={30}
    durationInFrames={sample.durationInFrames}
    defaultProps={sample}
    calculateMetadata={calculateMetadata}
  />
);
