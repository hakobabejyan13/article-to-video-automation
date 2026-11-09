import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import React, {useEffect, useMemo, useState} from 'react';
import {AbsoluteFill, Html5Audio, Sequence, cancelRender, continueRender, delayRender, staticFile} from 'remotion';
import {layoutScene} from './layout';
import {SceneView} from './scenes/SceneView';
import {COLORS, FONT} from './theme';
import type {VideoProps} from './types';

const WEIGHTS = [400, 500, 600, 700];

export const Main: React.FC<VideoProps> = (props) => {
  const [handle] = useState(() => delayRender('Loading the Inter font'));
  const [ready, setReady] = useState(false);
  const sample = useMemo(
    () => props.scenes.flatMap((s) => [...s.onScreen.map((t) => t.text), s.sourceTag ?? '',
      ...(s.visual.items ?? []).flatMap((i) => [i.label, i.value])]).join(' ') || 'Aa',
    [props.scenes],
  );

  useEffect(() => {
    Promise.all(WEIGHTS.map((w) => document.fonts.load(`${w} 40px ${FONT}`, sample)))
      .then(() => {
        setReady(true);
        continueRender(handle);
      })
      .catch((err) => cancelRender(err));
  }, [handle, sample]);

  // Lay out every scene once, before any frame is drawn: a text that cannot fit
  // fails the whole render at once, naming its scene.
  const layouts = useMemo(() => {
    if (!ready) {
      return null;
    }
    try {
      return props.scenes.map((s) => layoutScene(s, props.minFontPx));
    } catch (err) {
      cancelRender(err);
      return null;
    }
  }, [ready, props.scenes, props.minFontPx]);

  return (
    <AbsoluteFill style={{background: `linear-gradient(135deg, ${COLORS.bgFrom}, ${COLORS.bgTo})`, fontFamily: FONT}}>
      {layouts
        ? props.scenes.map((scene, i) => (
            <Sequence key={scene.id} from={scene.from} durationInFrames={scene.durationInFrames} name={`Scene ${scene.id}`}>
              <SceneView scene={scene} layout={layouts[i]} />
              {scene.audio ? <Html5Audio src={staticFile(scene.audio)} /> : null}
            </Sequence>
          ))
        : null}
    </AbsoluteFill>
  );
};
