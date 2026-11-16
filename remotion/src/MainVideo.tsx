import React from "react";
import { Sequence } from "remotion";
import { SceneAppleGlass } from "./scenes/SceneAppleGlass";
import { ScenePunkZine } from "./scenes/ScenePunkZine";
import { SceneBroadcastNews } from "./scenes/SceneBroadcastNews";
import { SceneCyberpunkHUD } from "./scenes/SceneCyberpunkHUD";
import { SceneAcidPopClimax } from "./scenes/SceneAcidPopClimax";
import { StressTestHUD } from "./scenes/StressTestHUD";

export interface MainVideoProps {
  title?: string;
}

export const MainVideo: React.FC<MainVideoProps> = () => {
  return (
    <div
      style={{
        width: 1920,
        height: 1080,
        backgroundColor: "#000000",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Realtime Stress Test HUD Telemetry Overlay (always visible across all frames) */}
      <StressTestHUD />

      {/* Style 1: 0s - 1s (Frames 0 - 29) */}
      <Sequence durationInFrames={30} name="Style 1 - Apple Glassmorphism">
        <SceneAppleGlass />
      </Sequence>

      {/* Style 2: 1s - 2s (Frames 30 - 59) */}
      <Sequence from={30} durationInFrames={30} name="Style 2 - Punk Zine Collage">
        <ScenePunkZine />
      </Sequence>

      {/* Style 3: 2s - 3s (Frames 60 - 89) */}
      <Sequence from={60} durationInFrames={30} name="Style 3 - Broadcast News">
        <SceneBroadcastNews />
      </Sequence>

      {/* Style 4: 3s - 4s (Frames 90 - 119) */}
      <Sequence from={90} durationInFrames={30} name="Style 4 - Cyberpunk HUD">
        <SceneCyberpunkHUD />
      </Sequence>

      {/* Style 5: 4s - 5s (Frames 120 - 149) */}
      <Sequence from={120} durationInFrames={30} name="Style 5 - Acid Pop Climax">
        <SceneAcidPopClimax />
      </Sequence>
    </div>
  );
};
