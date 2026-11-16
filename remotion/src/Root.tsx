import React from "react";
import { Composition } from "remotion";
import { MainVideo } from "./MainVideo";
import { SceneAppleGlass } from "./scenes/SceneAppleGlass";
import { ScenePunkZine } from "./scenes/ScenePunkZine";
import { SceneBroadcastNews } from "./scenes/SceneBroadcastNews";
import { SceneCyberpunkHUD } from "./scenes/SceneCyberpunkHUD";
import { SceneAcidPopClimax } from "./scenes/SceneAcidPopClimax";

import { JuliaBurnoutinho } from "./JuliaBurnoutinho";
import { GameplayShortTemplate } from "./GameplayShortTemplate";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Gameplay Shorts Vertical 9:16 Template (30s default preview) */}
      <Composition
        id="GameplayShortTemplate"
        component={GameplayShortTemplate}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          title: "CLUTCH INSANO",
          hookText: "OLHA O QUE ACONTECEU AQUI!",
          durationType: "30s",
          accentColor: "#00E6FF",
        }}
      />

      {/* Julia Burnoutinho - Cute 9:16 Vertical Motion Design (5s) */}
      <Composition
        id="JuliaBurnoutinho"
        component={JuliaBurnoutinho}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
      />

      {/* Complete 5-Second 5-Style Stress Test */}
      <Composition
        id="OlaMundoStressTest"
        component={MainVideo}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          title: "Olá Mundo",
        }}
      />

      {/* Individual Scene Compositions for isolated Studio inspection */}
      <Composition
        id="Style1-AppleGlass"
        component={SceneAppleGlass}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
      />

      <Composition
        id="Style2-PunkZine"
        component={ScenePunkZine}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
      />

      <Composition
        id="Style3-BroadcastNews"
        component={SceneBroadcastNews}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
      />

      <Composition
        id="Style4-CyberpunkHUD"
        component={SceneCyberpunkHUD}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
      />

      <Composition
        id="Style5-AcidPopClimax"
        component={SceneAcidPopClimax}
        durationInFrames={30}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
