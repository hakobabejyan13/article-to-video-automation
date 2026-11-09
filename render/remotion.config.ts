// Remotion settings used by `remotion render` (pipeline/render.py passes the
// per-run values: props, concurrency, public dir, output file).
import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setOverwriteOutput(true);
