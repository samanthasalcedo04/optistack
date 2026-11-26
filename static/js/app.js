/**
 * Controlador Principal de la Plataforma OptiStack HMI 3D Dashboard.
 * Coordina el Visor 3D (Three.js), WebSockets en tiempo real, KPIs ISA-101,
 * Simulador IoT y los módulos CRUD de Camiones y Rutas con Carga Masiva Excel.
 */

const OptiStackApp = {
    viewer3d: null,
    currentMap: null,
    ws: null,
    autoStreamTimer: null,

    async init() {
        this._setupTabsNavigation();
        this._setup3DViewer();
        this._setupToolbarAndSliders();
        this._setupTelemetryActions();

        window.TrucksCRUDModule.init();
        window.AgenciesCRUDModule.init();

        await this.loadSystemStatus();
        await window.TrucksCRUDModule.loadTrucks();
        await window.AgenciesCRUDModule.loadAgencies();
        await this.refreshActiveMap(false);

        this._connectWebSocket();
        this._suggestNextGuideId();
    },

    _setupTabsNavigation() {
        const tabs = document.querySelectorAll(".nav-tab");
        tabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                tabs.forEach((t) => t.classList.remove("active"));
                tab.classList.add("active");

                const targetId = tab.getAttribute("data-target");
                document.querySelectorAll(".view-section").forEach((sec) => {
                    sec.classList.toggle("active", sec.id === targetId);
                });

                if (targetId === "view-visualizer" && this.viewer3d) {
                    setTimeout(() => this.viewer3d.handleResize(), 60);
                }
            });
        });
    },

    _setup3DViewer() {
        this.viewer3d = new window.StowageViewer3D("three-canvas-wrapper", (selectedPkg) => {
            this._renderFloatingInspector(selectedPkg);
            this._highlightFeedCard(selectedPkg ? selectedPkg.PackageID : null);
        });
    },

    _setupToolbarAndSliders() {
        // Vistas de cámara
        document.querySelectorAll("[data-cam]").forEach((btn) => {
            btn.addEventListener("click", () => {
                document.querySelectorAll("[data-cam]").forEach((b) => b.classList.remove("active"));
                btn.classList.add("active");
                this.viewer3d.setCameraPreset(btn.getAttribute("data-cam"));
            });
        });

        // Modos de coloración
        document.querySelectorAll("[data-colormode]").forEach((btn) => {
            btn.addEventListener("click", () => {
                document.querySelectorAll("[data-colormode]").forEach((b) => b.classList.remove("active"));
                btn.classList.add("active");
                this.viewer3d.colorMode = btn.getAttribute("data-colormode");
                this.viewer3d._rebuildPackagesMeshes(false);
            });
        });

        // Botón Rayos-X
        const xrayBtn = document.getElementById("btn-toggle-xray");
        if (xrayBtn) {
            xrayBtn.addEventListener("click", () => {
                this.viewer3d.xrayEnabled = !this.viewer3d.xrayEnabled;
                xrayBtn.classList.toggle("active", this.viewer3d.xrayEnabled);
                this.viewer3d.applyVisibilityFilters();
            });
        }

        // Slider de Corte Longitudinal (Eje X)
        const sliceSlider = document.getElementById("slider-slice-x");
        const sliceLabel = document.getElementById("label-slice-x");
        if (sliceSlider) {
            sliceSlider.addEventListener("input", () => {
                const val = parseInt(sliceSlider.value, 10);
                sliceLabel.textContent = `${val}%`;
                this.viewer3d.sliceXPercent = val;
                this.viewer3d.applyVisibilityFilters();
            });
        }

        // Scrubber Paso a Paso
        const stepSlider = document.getElementById("slider-step-scrubber");
        const stepLabel = document.getElementById("label-step-scrubber");
        if (stepSlider) {
            stepSlider.addEventListener("input", () => {
                const step = parseInt(stepSlider.value, 10);
                const total = this.currentMap ? this.currentMap.packages.length : 0;
                stepLabel.textContent = `${step} / ${total}`;
                this.viewer3d.maxSequenceVisible = step;
                this.viewer3d.applyVisibilityFilters();
            });
        }

        // Botón Reset Filtro de Agencia
        const resetAgencyBtn = document.getElementById("btn-Reset-agency-filter");
        if (resetAgencyBtn) {
            resetAgencyBtn.addEventListener("click", () => {
                this.viewer3d.activeAgencyFilter = null;
                this.viewer3d.applyVisibilityFilters();
                document.querySelectorAll(".agency-row-item").forEach((el) => el.classList.remove("active-filter"));
            });
        }

        // Eliminar paquete desde el inspector flotante
        const delPkgBtn = document.getElementById("btn-delete-selected-pkg");
        if (delPkgBtn) {
            delPkgBtn.addEventListener("click", async () => {
                if (!this.viewer3d.selectedPackageId) return;
                const pkgId = this.viewer3d.selectedPackageId;
                this.viewer3d.selectPackageById(null);
                await fetch(`/api/stowage/packages/${pkgId}`, { method: "DELETE" });
            });
        }
    },

    _setupTelemetryActions() {
        // Cambiar o iniciar estiba con el furgón elegido en la barra superior
        const newSessionBtn = document.getElementById("btn-new-session-from-truck");
        const truckSelect = document.getElementById("active-truck-selector");
        if (newSessionBtn && truckSelect) {
            newSessionBtn.addEventListener("click", async () => {
                const truckId = parseInt(truckSelect.value, 10);
                if (truckId) {
                    await this.startNewStowageWithTruck(truckId, false);
                }
            });
            truckSelect.addEventListener("change", async () => {
                const truckId = parseInt(truckSelect.value, 10);
                if (truckId) {
                    await this.startNewStowageWithTruck(truckId, false);
                }
            });
        }

        // Vaciar paquetes del mapa actual
        const clearBtn = document.getElementById("btn-clear-current-map");
        if (clearBtn) {
            clearBtn.addEventListener("click", async () => {
                if (!this.currentMap) return;
                await fetch(`/api/stowage/maps/${this.currentMap.StowageMapID}/clear`, { method: "POST" });
                this.showToast("Contenedor vaciado. Listo para nueva carga 3D.");
            });
        }

        // Re-optimizar estiba completa con Inteligencia Artificial
        const aiOptBtn = document.getElementById("btn-ai-reoptimize");
        if (aiOptBtn) {
            aiOptBtn.addEventListener("click", async () => {
                if (!this.currentMap) return;
                aiOptBtn.disabled = true;
                aiOptBtn.textContent = "⏳ Optimizando con IA...";
                try {
                    const res = await fetch(`/api/stowage/maps/${this.currentMap.StowageMapID}/ai-reoptimize`, { method: "POST" });
                    if (res.ok) {
                        const data = await res.json();
                        this.applyStowageMapUpdate(data, false);
                        this.showToast("🤖 ¡Estiba optimizada con éxito por el modelo de IA!");
                    } else {
                        let msg = "Error al optimizar con IA";
                        try {
                            const err = await res.json();
                            msg = err.detail || msg;
                        } catch (_) {}
                        this.showToast(msg, "danger");
                    }
                } catch (e) {
                    console.error("AI Reoptimize error:", e);
                    this.showToast("Error de conexión con el motor de IA: " + (e.message || ""), "danger");
                } finally {
                    aiOptBtn.disabled = false;
                    aiOptBtn.textContent = "🤖 Optimizar IA";
                }
            });
        }

        // Carga Masiva de Manifiesto Excel para IA
        const uploadPkgsInput = document.getElementById("ai-packages-file");
        const selectPkgsBtn = document.getElementById("btn-select-ai-packages-file");
        if (selectPkgsBtn && uploadPkgsInput) {
            selectPkgsBtn.addEventListener("click", () => uploadPkgsInput.click());
            uploadPkgsInput.addEventListener("change", async (e) => {
                const file = e.target.files[0];
                if (!file || !this.currentMap) return;
                const formData = new FormData();
                formData.append("file", file);
                selectPkgsBtn.disabled = true;
                selectPkgsBtn.textContent = "⏳ IA Procesando Manifiesto...";
                try {
                    const res = await fetch(`/api/stowage/maps/${this.currentMap.StowageMapID}/excel/packages`, {
                        method: "POST",
                        body: formData
                    });
                    if (res.ok) {
                        const data = await res.json();
                        this.applyStowageMapUpdate(data, false);
                        this.showToast(`🤖 ¡Manifiesto estibado exitosamente por la IA! (${data.packages.length} paquetes)`);
                    } else {
                        let msg = "Error procesando archivo";
                        try {
                            const err = await res.json();
                            msg = err.detail || msg;
                        } catch (_) {}
                        this.showToast(msg, "danger");
                    }
                } catch (err) {
                    console.error("Excel upload error:", err);
                    this.showToast("Error subiendo manifiesto: " + (err.message || ""), "danger");
                } finally {
                    selectPkgsBtn.disabled = false;
                    selectPkgsBtn.textContent = "📁 Subir Manifiesto de Paquetes (.xlsx)";
                    uploadPkgsInput.value = "";
                }
            });
        }

        // Simular 1 paquete IoT (Raspberry Pi / ESP32)
        const simSingleBtn = document.getElementById("btn-sim-single-pkg");
        if (simSingleBtn) {
            simSingleBtn.addEventListener("click", async () => {
                await this.triggerSimulatedPackage();
            });
        }

        // Auto-Stream continuo de paquetes IoT
        const autoBtn = document.getElementById("btn-toggle-auto-stream");
        if (autoBtn) {
            autoBtn.addEventListener("click", () => {
                if (this.autoStreamTimer) {
                    clearInterval(this.autoStreamTimer);
                    this.autoStreamTimer = null;
                    autoBtn.innerHTML = "&#9654; Auto-Stream IoT";
                    autoBtn.classList.remove("btn-emerald");
                    autoBtn.classList.add("btn-outline");
                    this.showToast("Auto-Stream IoT pausado");
                } else {
                    autoBtn.innerHTML = "&#9208; Detener Stream";
                    autoBtn.classList.remove("btn-outline");
                    autoBtn.classList.add("btn-emerald");
                    this.triggerSimulatedPackage();
                    this.autoStreamTimer = setInterval(() => this.triggerSimulatedPackage(), 2100);
                }
            });
        }

        // Formulario de ingreso manual de paquete
        const manualForm = document.getElementById("manual-package-form");
        if (manualForm) {
            manualForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                const payload = {
                    GuideID: document.getElementById("inp-pkg-guide").value.trim(),
                    TargetAgencyID: document.getElementById("inp-pkg-agency").value,
                    LengthCm: parseFloat(document.getElementById("inp-pkg-l").value),
                    WidthCm: parseFloat(document.getElementById("inp-pkg-w").value),
                    HeightCm: parseFloat(document.getElementById("inp-pkg-h").value),
                    WeightKg: parseFloat(document.getElementById("inp-pkg-weight").value),
                    StowageMapID: this.currentMap ? this.currentMap.StowageMapID : null,
                    SourceDevice: "HMI-Operator-Terminal",
                };

                const res = await fetch("/api/stowage/telemetry/package", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });

                if (!res.ok) {
                    const err = await res.json();
                    this.showToast(err.detail || "No se pudo estibar el paquete", "error");
                    return;
                }
                const data = await res.json();
                this.applyStowageMapUpdate(data, true);
                this._suggestNextGuideId();
            });
        }
    },

    _suggestNextGuideId() {
        const inp = document.getElementById("inp-pkg-guide");
        if (!inp) return;
        const nextNum = 2001 + (this.currentMap ? this.currentMap.packages.length : 0);
        inp.value = `GUIA-${nextNum}`;
    },

    async triggerSimulatedPackage() {
        const mapId = this.currentMap ? this.currentMap.StowageMapID : "";
        const res = await fetch(`/api/stowage/telemetry/simulate-random?map_id=${mapId}`, {
            method: "POST",
        });
        if (!res.ok) {
            const err = await res.json();
            this.showToast(err.detail || "Error en telemetría simulada", "error");
            return;
        }
        const data = await res.json();
        this.applyStowageMapUpdate(data, true);
    },

    async startNewStowageWithTruck(truckId, switchToVisualizerTab = true) {
        const res = await fetch("/api/stowage/maps", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                TruckID: truckId,
                RouteSummary: "Estiba Dinámica 3D - Medidas Personalizadas",
            }),
        });
        if (!res.ok) {
            const err = await res.json();
            this.showToast(err.detail || "No se pudo iniciar el mapa de estiba", "error");
            return;
        }
        const mapData = await res.json();
        this.applyStowageMapUpdate(mapData, false);
        this.showToast(`Contenedor 3D ajustado a ${mapData.TruckPlate} (${mapData.LengthCm}×${mapData.WidthCm}×${mapData.HeightCm} cm)`);

        if (switchToVisualizerTab) {
            document.getElementById("tab-btn-visualizer").click();
        }
    },

    async loadSystemStatus() {
        try {
            const res = await fetch("/api/system/status");
            if (!res.ok) return;
            const info = await res.json();
            const dbLabel = document.getElementById("db-engine-label");
            if (dbLabel) dbLabel.textContent = info.database_engine;
        } catch (_) {}
    },

    async refreshActiveMap(animateLatest = false) {
        const res = await fetch("/api/stowage/maps/active");
        if (!res.ok) return;
        const data = await res.json();
        this.applyStowageMapUpdate(data, animateLatest);
    },

    applyStowageMapUpdate(mapData, animateLatest = false) {
        this.currentMap = mapData;
        window.TrucksCRUDModule.populateTopbarSelector();

        // Actualizar Scrubber Paso a Paso
        const totalPkgs = mapData.packages.length;
        const stepSlider = document.getElementById("slider-step-scrubber");
        const stepLabel = document.getElementById("label-step-scrubber");
        if (stepSlider && stepLabel) {
            stepSlider.max = totalPkgs;
            stepSlider.value = totalPkgs;
            stepLabel.textContent = `${totalPkgs} / ${totalPkgs}`;
            this.viewer3d.maxSequenceVisible = totalPkgs;
        }

        // Actualizar el Visor 3D
        this.viewer3d.updateStowageData(mapData, animateLatest);

        // Actualizar Franja de KPIs Superiores
        this._renderKPIs(mapData);

        // Actualizar Leyenda de Zonas por Agencia y Bitácora Lateral
        this._renderAgencyBreakdown(mapData.kpis.agency_breakdown);
        this._renderPackageFeed(mapData.packages);
        this._suggestNextGuideId();
    },

    _renderKPIs(mapData) {
        const { kpis } = mapData;
        document.getElementById("kpi-truck-dims").innerHTML =
            `${mapData.LengthCm} &times; ${mapData.WidthCm} &times; ${mapData.HeightCm} cm`;

        document.getElementById("kpi-vol-m3").innerHTML =
            `${kpis.occupied_volume_m3.toFixed(2)} / ${kpis.container_volume_m3.toFixed(2)} m&sup3;`;
        document.getElementById("kpi-vol-pct").textContent = `${kpis.volume_utilization_pct.toFixed(1)}%`;
        document.getElementById("kpi-vol-bar").style.width = `${Math.min(100, kpis.volume_utilization_pct)}%`;

        document.getElementById("kpi-weight-kg").textContent =
            `${kpis.total_weight_kg.toFixed(1)} / ${kpis.max_weight_kg.toFixed(0)} kg`;
        document.getElementById("kpi-weight-pct").textContent = `${kpis.weight_utilization_pct.toFixed(1)}%`;
        const wBar = document.getElementById("kpi-weight-bar");
        wBar.style.width = `${Math.min(100, kpis.weight_utilization_pct)}%`;
        wBar.className =
            "progress-fill " +
            (kpis.weight_utilization_pct > 95
                ? "critical"
                : kpis.weight_utilization_pct > 80
                ? "warning"
                : "emerald");

        document.getElementById("kpi-pkg-count").textContent = kpis.total_packages;
        if (mapData.packages.length > 0) {
            const last = mapData.packages[mapData.packages.length - 1];
            document.getElementById("kpi-last-guide").textContent = `Última: ${last.GuideID}`;
            document.getElementById("kpi-last-source").textContent = last.SourceDevice;
        } else {
            document.getElementById("kpi-last-guide").textContent = "Contenedor vacío";
        }

        document.getElementById("kpi-cog-coords").textContent =
            `X:${kpis.cog_x_cm} Y:${kpis.cog_y_cm} Z:${kpis.cog_z_cm} cm`;
        document.getElementById("kpi-cog-offset").textContent =
            `Lat: ${kpis.cog_z_Offset_pct > 0 ? "+" : ""}${kpis.cog_z_Offset_pct}%`;

        const stabBadge = document.getElementById("kpi-stability-badge");
        stabBadge.textContent = kpis.stability_status;
        stabBadge.style.color =
            kpis.stability_status === "CRITICAL"
                ? "#ef4444"
                : kpis.stability_status === "WARNING"
                ? "#f59e0b"
                : "#10b981";
    },

    _renderAgencyBreakdown(breakdown) {
        const container = document.getElementById("sidebar-agency-breakdown");
        if (!container) return;
        container.innerHTML = "";

        if (!breakdown || breakdown.length === 0) {
            container.innerHTML = `<div style="font-size:12px; color:var(--text-muted);">Aún no hay paquetes estibados en este contenedor.</div>`;
            return;
        }

        breakdown.forEach((item) => {
            const row = document.createElement("div");
            row.className =
                "agency-row-item" + (this.viewer3d.activeAgencyFilter === item.AgencyID ? " active-filter" : "");
            row.innerHTML = `
                <div style="display:flex; align-items:center;">
                    <span class="agency-swatch" style="background:${item.ColorHex};"></span>
                    <div>
                        <div style="font-weight:600; font-size:12.5px; color:var(--text-primary);">
                            ${item.AgencyName}
                        </div>
                        <div style="font-size:10.5px; color:var(--text-muted); font-family:var(--font-mono);">
                            ${item.AgencyID} &bull; ${item.RouteCode} &bull; LIFO Zona ${item.ZoneOrder}
                        </div>
                    </div>
                </div>
                <div style="text-align:right; font-family:var(--font-mono); font-size:11.5px;">
                    <strong style="color:var(--accent-cyan);">${item.package_count} bultos</strong>
                    <div style="color:var(--text-muted); font-size:10.5px;">${item.total_weight_kg} kg</div>
                </div>
            `;
            row.addEventListener("click", () => {
                if (this.viewer3d.activeAgencyFilter === item.AgencyID) {
                    this.viewer3d.activeAgencyFilter = null;
                } else {
                    this.viewer3d.activeAgencyFilter = item.AgencyID;
                }
                this.viewer3d.applyVisibilityFilters();
                this._renderAgencyBreakdown(breakdown);
            });
            container.appendChild(row);
        });
    },

    _renderPackageFeed(packages) {
        const container = document.getElementById("package-feed-container");
        const counter = document.getElementById("feed-counter-label");
        if (counter) counter.textContent = `${packages.length} ítems`;
        if (!container) return;

        container.innerHTML = "";
        const reversed = [...packages].reverse();
        reversed.forEach((pkg) => {
            const card = document.createElement("div");
            card.className = "pkg-feed-card";
            card.setAttribute("data-pkg-card-id", pkg.PackageID);
            card.style.borderLeftColor = pkg.ColorHex || "#38bdf8";

            card.innerHTML = `
                <div class="pkg-feed-meta">
                    <span class="pkg-feed-guide">#${pkg.SequenceOrder} &bull; ${pkg.GuideID}</span>
                    <span class="pkg-feed-sub">
                        ${pkg.AgencyName || pkg.TargetAgencyID} | ${pkg.LengthCm}&times;${pkg.WidthCm}&times;${pkg.HeightCm}cm | ${pkg.WeightKg}kg
                    </span>
                </div>
                <div style="text-align:right; font-family:var(--font-mono); font-size:11px; color:var(--accent-cyan);">
                    <div>X:${pkg.CoordX}</div>
                    <div>Y:${pkg.CoordY} Z:${pkg.CoordZ}</div>
                </div>
            `;

            card.addEventListener("click", () => {
                this.viewer3d.selectPackageById(pkg.PackageID);
            });
            container.appendChild(card);
        });
    },

    _renderFloatingInspector(pkg) {
        const box = document.getElementById("floating-pkg-inspector");
        if (!box) return;
        if (!pkg) {
            box.classList.add("hidden");
            return;
        }
        box.classList.remove("hidden");
        document.getElementById("insp-guide-id").textContent = pkg.GuideID;
        document.getElementById("insp-seq").textContent = `Secuencia #${pkg.SequenceOrder}`;
        document.getElementById("insp-agency").textContent = `${pkg.AgencyName || pkg.TargetAgencyID} (${pkg.RouteCode || ""})`;
        document.getElementById("insp-zone").textContent = `LIFO Zona ${pkg.ZoneOrder || 1}`;
        document.getElementById("insp-dims").innerHTML = `${pkg.LengthCm}&times;${pkg.WidthCm}&times;${pkg.HeightCm} cm`;
        document.getElementById("insp-weight").textContent = `${pkg.WeightKg} kg`;
        document.getElementById("insp-coords").textContent = `(${pkg.CoordX}, ${pkg.CoordY}, ${pkg.CoordZ}) cm`;
        document.getElementById("insp-rot").textContent = pkg.RotationState;
    },

    _highlightFeedCard(pkgId) {
        document.querySelectorAll(".pkg-feed-card").forEach((c) => {
            const cid = parseInt(c.getAttribute("data-pkg-card-id"), 10);
            c.classList.toggle("selected", cid === pkgId);
        });
    },

    _connectWebSocket() {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${proto}//${window.location.host}/ws/stowage`;
        const dot = document.getElementById("ws-status-dot");
        const txt = document.getElementById("ws-status-text");

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            if (dot) dot.classList.remove("disconnected");
            if (txt) txt.textContent = "Telemetría Live (WS)";
        };

        this.ws.onmessage = async (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (
                    msg.event === "PACKAGE_INGESTED" ||
                    msg.event === "STOWAGE_MAP_SWITCHED" ||
                    msg.event === "STOWAGE_MAP_CLEARED" ||
                    msg.event === "PACKAGE_REMOVED"
                ) {
                    if (msg.stowage_map) {
                        this.applyStowageMapUpdate(msg.stowage_map, msg.event === "PACKAGE_INGESTED");
                    }
                } else if (msg.event === "TRUCK_CATALOG_UPDATED") {
                    await window.TrucksCRUDModule.loadTrucks();
                    await this.refreshActiveMap(false);
                } else if (msg.event === "AGENCY_CATALOG_UPDATED") {
                    await window.AgenciesCRUDModule.loadAgencies();
                    await this.refreshActiveMap(false);
                }
            } catch (_) {}
        };

        this.ws.onclose = () => {
            if (dot) dot.classList.add("disconnected");
            if (txt) txt.textContent = "Reconectando WS...";
            setTimeout(() => this._connectWebSocket(), 3000);
        };
    },

    showToast(message, type = "info") {
        const container = document.getElementById("toast-container");
        if (!container) return;
        const toast = document.createElement("div");
        toast.className = "hmi-toast";
        if (type === "error") {
            toast.style.borderLeftColor = "#ef4444";
        }
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => {
            toast.remove();
        }, 3800);
    },
};

window.OptiStackApp = OptiStackApp;
window.addEventListener("DOMContentLoaded", () => {
    window.OptiStackApp.init();
});
