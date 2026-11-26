/**
 * Módulo UI CRUD de Gestión de Camiones / Furgones (TruckMaster).
 * Permite crear, editar, eliminar furgones con medidas personalizadas (L, A, H en cm)
 * y abrir una sesión de estiba 3D con cualquier camión del catálogo.
 */

const TrucksCRUDModule = {
    trucks: [],

    init() {
        const form = document.getElementById("crud-truck-form");
        const cancelBtn = document.getElementById("btn-cancel-truck-edit");

        ["truck-length", "truck-width", "truck-height"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.addEventListener("input", () => this.updateVolumePreview());
        });

        if (form) {
            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                await this.saveTruck();
            });
        }

        if (cancelBtn) {
            cancelBtn.addEventListener("click", () => this.resetForm());
        }
    },

    updateVolumePreview() {
        const l = parseFloat(document.getElementById("truck-length").value) || 0;
        const w = parseFloat(document.getElementById("truck-width").value) || 0;
        const h = parseFloat(document.getElementById("truck-height").value) || 0;
        const volM3 = (l * w * h) / 1000000.0;
        const preview = document.getElementById("truck-calc-vol-preview");
        if (preview) {
            preview.innerHTML = `${volM3.toFixed(2)} m&sup3;`;
        }
    },

    async loadTrucks() {
        const res = await fetch("/api/trucks");
        if (!res.ok) return;
        this.trucks = await res.json();
        this.renderTable();
        this.populateTopbarSelector();
    },

    renderTable() {
        const tbody = document.getElementById("trucks-table-body");
        const navCount = document.getElementById("nav-trucks-count");
        const badge = document.getElementById("table-trucks-badge");

        if (navCount) navCount.textContent = this.trucks.length;
        if (badge) badge.textContent = `${this.trucks.length} unidades`;
        if (!tbody) return;

        tbody.innerHTML = "";
        this.trucks.forEach((t) => {
            const volM3 = ((t.LengthCm * t.WidthCm * t.HeightCm) / 1000000.0).toFixed(2);
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td class="mono-cell" style="color: var(--accent-cyan);">${t.TruckPlate}</td>
                <td><strong>${t.TruckName}</strong></td>
                <td class="mono-cell">${t.LengthCm} &times; ${t.WidthCm} &times; ${t.HeightCm} cm</td>
                <td class="mono-cell">${volM3} m&sup3;</td>
                <td class="mono-cell">${t.MaxWeightKg.toLocaleString()} kg</td>
                <td style="text-align:right; white-space:nowrap;">
                    <button class="btn btn-emerald btn-sm" data-use-truck="${t.TruckID}" title="Abrir estiba 3D con este furgón">
                        &#9638; Usar en Visor 3D
                    </button>
                    <button class="btn btn-outline btn-sm" data-edit-truck="${t.TruckID}">
                        Editar
                    </button>
                    <button class="btn btn-danger btn-sm" data-del-truck="${t.TruckID}">
                        Eliminar
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll("[data-use-truck]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const truckId = parseInt(btn.getAttribute("data-use-truck"), 10);
                await window.OptiStackApp.startNewStowageWithTruck(truckId, true);
            });
        });

        tbody.querySelectorAll("[data-edit-truck]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const truckId = parseInt(btn.getAttribute("data-edit-truck"), 10);
                this.startEdit(truckId);
            });
        });

        tbody.querySelectorAll("[data-del-truck]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const truckId = parseInt(btn.getAttribute("data-del-truck"), 10);
                await this.deleteTruck(truckId);
            });
        });
    },

    populateTopbarSelector() {
        const sel = document.getElementById("active-truck-selector");
        if (!sel) return;
        const currentTruckId = window.OptiStackApp?.currentMap?.TruckID;
        sel.innerHTML = "";
        this.trucks.forEach((t) => {
            const opt = document.createElement("option");
            opt.value = t.TruckID;
            opt.textContent = `${t.TruckPlate} — ${t.TruckName} (${t.LengthCm}×${t.WidthCm}×${t.HeightCm} cm)`;
            if (currentTruckId && t.TruckID === currentTruckId) {
                opt.selected = true;
            }
            sel.appendChild(opt);
        });
    },

    startEdit(truckId) {
        const t = this.trucks.find((x) => x.TruckID === truckId);
        if (!t) return;

        document.getElementById("truck-edit-id").value = t.TruckID;
        document.getElementById("truck-plate").value = t.TruckPlate;
        document.getElementById("truck-name").value = t.TruckName;
        document.getElementById("truck-length").value = t.LengthCm;
        document.getElementById("truck-width").value = t.WidthCm;
        document.getElementById("truck-height").value = t.HeightCm;
        document.getElementById("truck-max-weight").value = t.MaxWeightKg;
        document.getElementById("truck-empty-weight").value = t.EmptyWeightKg;

        document.getElementById("truck-form-title").textContent = `Editando Furgón: ${t.TruckPlate}`;
        document.getElementById("btn-save-truck").textContent = "Actualizar Medidas del Furgón";
        document.getElementById("btn-cancel-truck-edit").style.display = "inline-flex";
        this.updateVolumePreview();
    },

    resetForm() {
        document.getElementById("crud-truck-form").reset();
        document.getElementById("truck-edit-id").value = "";
        document.getElementById("truck-form-title").textContent = "Registrar Nuevo Furgón / Camión";
        document.getElementById("btn-save-truck").textContent = "Guardar Furgón en Catálogo";
        document.getElementById("btn-cancel-truck-edit").style.display = "none";
        this.updateVolumePreview();
    },

    async saveTruck() {
        const editId = document.getElementById("truck-edit-id").value;
        const payload = {
            TruckPlate: document.getElementById("truck-plate").value.trim(),
            TruckName: document.getElementById("truck-name").value.trim(),
            LengthCm: parseFloat(document.getElementById("truck-length").value),
            WidthCm: parseFloat(document.getElementById("truck-width").value),
            HeightCm: parseFloat(document.getElementById("truck-height").value),
            MaxWeightKg: parseFloat(document.getElementById("truck-max-weight").value),
            EmptyWeightKg: parseFloat(document.getElementById("truck-empty-weight").value) || 0,
            IsActive: true,
        };

        const url = editId ? `/api/trucks/${editId}` : "/api/trucks";
        const method = editId ? "PUT" : "POST";

        const res = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            window.OptiStackApp.showToast(err.detail || "Error al guardar el furgón", "error");
            return;
        }

        window.OptiStackApp.showToast(
            editId ? "Medidas del furgón actualizadas correctamente" : "Nuevo furgón registrado en el catálogo"
        );
        this.resetForm();
        await this.loadTrucks();
        await window.OptiStackApp.refreshActiveMap(false);
    },

    async deleteTruck(truckId) {
        const res = await fetch(`/api/trucks/${truckId}`, { method: "DELETE" });
        if (res.ok) {
            window.OptiStackApp.showToast("Furgón eliminado del catálogo");
            await this.loadTrucks();
        }
    },
};

window.TrucksCRUDModule = TrucksCRUDModule;
