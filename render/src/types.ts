// Props of the Main composition. pipeline/render.py writes them to
// render/out/<id>.props.json from the scenes JSON and audio/<id>/timing.json.

export type Role = 'headline' | 'sub' | 'bullet' | 'quote';

export type TextItem = {role: Role; text: string};

export type Item = {label: string; value: string};

export type SceneProps = {
  id: number;
  from: number; // first frame of the scene in the video
  durationInFrames: number;
  audio: string | null; // WAV file name inside the public dir (audio/<id>/)
  lineStarts: number[]; // voiceover line starts, in frames from the scene start
  sourceTag: string | null; // fixed tag from config, never from the LLM
  visual: {type: string; variant?: string; icon?: string; items?: Item[]; scale?: number[]};
  // scale: bar_chart only, each bar's length as a share of the longest (pipeline/render.py bar_scale)
  onScreen: TextItem[];
};

export type VideoProps = {
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  minFontPx: number;
  scenes: SceneProps[];
};
