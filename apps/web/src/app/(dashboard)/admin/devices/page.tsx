"use client";

/**
 * /admin/devices — Device catalog management.
 *
 * Admins and instructors can view the available device types.
 * Adding custom devices (beyond the built-in Cisco catalog) is a
 * future feature pending the full admin panel spec.
 */

import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import { CheckCircle2, Clock, Monitor, Network, Server } from "lucide-react";
import { Laptop } from "lucide-react";

const ICON_MAP: Record<string, React.ElementType> = {
  pc:        Monitor,
  laptop:    Laptop,
  server:    Server,
  "switch-l2": Network,
  router:    Network,
};

export default function DevicesPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Device Catalog</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Simulated device types available for use in lab topologies.
          Custom devices can be added in a future admin panel release.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {DEFAULT_DEVICE_CATALOG.map((device) => {
          const Icon = ICON_MAP[device.icon] ?? Network;
          return (
            <Card key={device.id}>
              <CardBody className="flex items-start gap-4">
                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                  style={{
                    background: device.simulated
                      ? "var(--accent-subtle)"
                      : "var(--surface-overlay)",
                  }}
                  aria-hidden="true"
                >
                  <Icon
                    size={16}
                    className={
                      device.simulated
                        ? "text-[var(--accent-primary)]"
                        : "text-[var(--text-muted)]"
                    }
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="text-sm font-semibold text-[var(--text-primary)]">
                      {device.label}
                    </span>
                    {device.simulated ? (
                      <Badge variant="success">
                        <CheckCircle2 size={10} className="mr-1" />
                        Simulated
                      </Badge>
                    ) : (
                      <Badge variant="warning">
                        <Clock size={10} className="mr-1" />
                        Coming soon
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-[var(--text-muted)] font-mono mb-1">
                    {device.modelName}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                    {device.description}
                  </p>
                  <div className="flex gap-3 mt-2 text-[10px] font-mono text-[var(--text-muted)]">
                    <span>ID: {device.id}</span>
                    <span>Model: {device.model}</span>
                  </div>
                </div>
              </CardBody>
            </Card>
          );
        })}
      </div>

      <Card>
        <CardHeader>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            About the device catalog
          </h2>
        </CardHeader>
        <CardBody className="space-y-2 text-sm text-[var(--text-secondary)]">
          <p>
            The device catalog defines which device types appear in the
            topology editor palette. Each entry has an icon, model name,
            simulator model type (host or switch), and a simulated flag.
          </p>
          <p>
            Devices marked <span className="text-[var(--status-success)]">Simulated</span> are
            fully supported by the NetLab Academy simulator core. Devices
            marked <span className="text-[var(--status-warning)]">Coming soon</span> will be
            enabled in a future simulator release.
          </p>
          <p className="text-[var(--text-muted)] text-xs">
            Custom device types and admin management of the catalog are planned
            for the platform admin feature spec (EVE-NG-style device management).
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
