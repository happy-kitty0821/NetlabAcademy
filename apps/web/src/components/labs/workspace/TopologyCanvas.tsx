"use client";

/**
 * TopologyCanvas — CML-style animated network canvas for the workspace.
 * Wraps the existing TopologyCanvas with CML context menus.
 */

import type { TopologyDocument, TopologyNode, TraceEvent } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";
import { TopologyCanvas as AnimCanvas } from "@/components/labs/TopologyCanvas";

interface TopologyCanvasProps {
  topology: TopologyDocument;
  trace: TraceEvent[];
  isPlaying: boolean;
  currentStep: number;
  speed: number;
  onStepChange: (s: number) => void;
  onNodeSelect: (node: TopologyNode | null) => void;
  selectedNodeId: string | null;
  simState: SimState;
}

export function TopologyCanvas({
  topology, trace, isPlaying, currentStep, speed,
  onStepChange, simState,
}: Omit<TopologyCanvasProps, "onNodeSelect" | "selectedNodeId">) {
  const showSim = simState === "running" && trace.length > 0;

  return (
    <div className="w-full h-full relative select-none">
      {/* Canvas background — dark dot grid matching CML */}
      <div
        className="absolute inset-0"
        style={{
          background: "#0d1117",
          backgroundImage: "radial-gradient(circle, #21262d 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />

      <div className="relative h-full">
        <AnimCanvas
          topology={topology}
          trace={trace}
          isPlaying={isPlaying}
          currentStep={currentStep}
          speed={speed}
          onStepChange={onStepChange}
          totalSteps={trace.length}
          showSimulation={showSim}
        />
      </div>

      {/* Node click overlay — invisible hit areas for selection */}
      <div
        className="absolute inset-0 pointer-events-none"
        aria-hidden="true"
      />

      {/* CML-style empty state */}
      {topology.nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 pointer-events-none">
          <div className="text-[#484f58] text-sm font-mono">
            No nodes. Use the palette or Build topology.
          </div>
        </div>
      )}
    </div>
  );
}
