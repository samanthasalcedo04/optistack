/**
 * Módulo UI CRUD de Catálogo de Rutas / Agencias Destino (AgencyMaster)
 * + Carga Masiva mediante Archivo de Excel (.xlsx) y Descarga de Plantilla.
 */

const AgenciesCRUDModule = {
    agencies: [],
    selectedExcelFile: null,

    init() {
        const form = document.getElementById("crud-agency-form");
        const cancelBtn = document.getElementById("btn-cancel-agency-edit");
        const dropzone = document.getElementById("excel-dropzone");
        const fileInput = document.getElementById("excel-file-input");
        const uploadBtn = document.getElementById("btn-upload-excel");

        if (form) {
            form.addEventListener("submit", async (e) => {
                e.preventDefault();
                await this.saveAgency();
            });
        }

        if (cancelBtn) {
            cancelBtn.addEventListener("click", () => this.resetForm());
        }

        if (dropzone && fileInput) {
            dropzone.addEventListener("click", () => fileInput.click());

            dropzone.addEventListener("dragover", (e) => {
                e.preventDefault();
                dropzone.classList.add("dragover");
            });

            dropzone.addEventListener("dragleave", () => {
                dropzone.classList.remove("dragover");
            });

            dropzone.addEventListener("drop", (e) => {
                e.preventDefault();
                dropzone.classList.remove("dragover");
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    this.setExcelFile(e.dataTransfer.files[0]);
                }
            });

            fileInput.addEventListener("change", () => {
                if (fileInput.files && fileInput.files.length > 0) {
                    this.setExcelFile(fileInput.files[0]);
                }
            });
        }

        if (uploadBtn) {
            uploadBtn.addEventListener("click", async () => {
                await this.uploadExcelFile();
            });
        }
    },

    setExcelFile(file) {
        this.selectedExcelFile = file;
        const label = document.getElementById("excel-selected-filename");
        if (label) {
            label.textContent = `Archivo listo: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            label.style.color = "#10b981";
        }
    },

    async uploadExcelFile() {
        if (!this.selectedExcelFile) {
            window.OptiStackApp.showToast("Selecciona primero un archivo Excel (.xlsx) para importar", "error");
            return;
        }

        const formData = new FormData();
        formData.append("file", this.selectedExcelFile);

        const res = await fetch("/api/agencies/excel/upload", {
            method: "POST",
            body: formData,
        });

        const feedbackBox = document.getElementById("excel-import-feedback");
        if (!res.ok) {
            const err = await res.json();
            window.OptiStackApp.showToast(err.detail || "Error al procesar el archivo Excel", "error");
            return;
        }

        const result = await res.json();
        if (feedbackBox) {
            feedbackBox.style.display = "block";
            feedbackBox.innerHTML = `
                <div style="padding:8px 10px; background:rgba(16,185,129,0.14); border:1px solid #10b981; border-radius:6px; color:#e2e8f0;">
                    <strong>Resultado Carga Masiva Excel:</strong>
                    Filas leídas: <b>${result.total_rows_read}</b> |
                    Nuevas insertadas: <b style="color:#10b981;">${result.inserted_count}</b> |
                    Actualizadas: <b style="color:#38bdf8;">${result.updated_count}</b> |
                    Omitidas: <b>${result.skipped_count}</b>
                </div>
            `;
        }

        window.OptiStackApp.showToast(
            `Carga masiva Excel completada: ${result.inserted_count} nuevas, ${result.updated_count} actualizadas`
        );
        await this.loadAgencies();
        await window.OptiStackApp.refreshActiveMap(false);
    },

    async loadAgencies() {
        const res = await fetch("/api/agencies");
        if (!res.ok) return;
        this.agencies = await res.json();
        this.renderTable();
        this.populateManualPackageAgencySelect();
    },

    renderTable() {
        const tbody = document.getElementById("agencies-table-body");
        const navCount = document.getElementById("nav-agencies-count");
        const badge = document.getElementById("table-agencies-badge");

        if (navCount) navCount.textContent = this.agencies.length;
        if (badge) badge.textContent = `${this.agencies.length} rutas`;
        if (!tbody) return;

        tbody.innerHTML = "";
        this.agencies.forEach((ag) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>
                    <span class="agency-swatch" style="background:${ag.ColorHex}; width:18px; height:18px; vertical-align:middle;"></span>
                    <span class="mono-cell" style="font-size:11.5px;">${ag.ColorHex}</span>
                </td>
                <td class="mono-cell" style="color: var(--accent-cyan);">${ag.AgencyID}</td>
                <td><strong>${ag.AgencyName}</strong></td>
                <td class="mono-cell">${ag.RouteCode}</td>
                <td class="mono-cell">Zona ${ag.ZoneOrder}</td>
                <td>${ag.City || "—"}</td>
                <td style="text-align:right; white-space:nowrap;">
                    <button class="btn btn-outline btn-sm" data-edit-agency="${ag.AgencyID}">
                        Editar
                    </button>
                    <button class="btn btn-danger btn-sm" data-del-agency="${ag.AgencyID}">
                        Eliminar
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll("[data-edit-agency]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-edit-agency");
                this.startEdit(id);
            });
        });

        tbody.querySelectorAll("[data-del-agency]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-del-agency");
                await this.deleteAgency(id);
            });
        });
    },

    populateManualPackageAgencySelect() {
        const sel = document.getElementById("inp-pkg-agency");
        if (!sel) return;
        const prev = sel.value;
        sel.innerHTML = "";
        this.agencies.forEach((ag) => {
            const opt = document.createElement("option");
            opt.value = ag.AgencyID;
            opt.textContent = `${ag.AgencyID} — ${ag.AgencyName} (LIFO ${ag.ZoneOrder})`;
            if (prev && prev === ag.AgencyID) opt.selected = true;
            sel.appendChild(opt);
        });
    },

    startEdit(agencyId) {
        const ag = this.agencies.find((a) => a.AgencyID === agencyId);
        if (!ag) return;

        document.getElementById("agency-edit-mode").value = "edit";
        const idInput = document.getElementById("agency-id");
        idInput.value = ag.AgencyID;
        idInput.readOnly = true;

        document.getElementById("agency-name").value = ag.AgencyName;
        document.getElementById("agency-route-code").value = ag.RouteCode;
        document.getElementById("agency-zone-order").value = ag.ZoneOrder;
        document.getElementById("agency-city").value = ag.City || "";
        document.getElementById("agency-color").value = ag.ColorHex;

        document.getElementById("agency-form-title").textContent = `Editando Ruta: ${ag.AgencyID}`;
        document.getElementById("btn-save-agency").textContent = "Actualizar Ruta / Agencia";
        document.getElementById("btn-cancel-agency-edit").style.display = "inline-flex";
    },

    resetForm() {
        document.getElementById("crud-agency-form").reset();
        document.getElementById("agency-edit-mode").value = "create";
        const idInput = document.getElementById("agency-id");
        idInput.readOnly = false;
        document.getElementById("agency-form-title").textContent = "Registrar / Editar Ruta o Agencia";
        document.getElementById("btn-save-agency").textContent = "Guardar Ruta / Agencia";
        document.getElementById("btn-cancel-agency-edit").style.display = "none";
    },

    async saveAgency() {
        const mode = document.getElementById("agency-edit-mode").value;
        const agencyId = document.getElementById("agency-id").value.trim().toUpperCase();

        const payload = {
            AgencyID: agencyId,
            AgencyName: document.getElementById("agency-name").value.trim(),
            RouteCode: document.getElementById("agency-route-code").value.trim().toUpperCase(),
            ZoneOrder: parseInt(document.getElementById("agency-zone-order").value, 10) || 1,
            City: document.getElementById("agency-city").value.trim(),
            ColorHex: document.getElementById("agency-color").value,
            IsActive: true,
        };

        const url = mode === "edit" ? `/api/agencies/${encodeURIComponent(agencyId)}` : "/api/agencies";
        const method = mode === "edit" ? "PUT" : "POST";

        const res = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            window.OptiStackApp.showToast(err.detail || "Error al guardar la ruta/agencia", "error");
            return;
        }

        window.OptiStackApp.showToast(
            mode === "edit" ? `Ruta ${agencyId} actualizada` : `Ruta ${agencyId} agregada al catálogo`
        );
        this.resetForm();
        await this.loadAgencies();
        await window.OptiStackApp.refreshActiveMap(false);
    },

    async deleteAgency(agencyId) {
        const res = await fetch(`/api/agencies/${encodeURIComponent(agencyId)}`, { method: "DELETE" });
        if (res.ok) {
            window.OptiStackApp.showToast(`Ruta ${agencyId} eliminada del catálogo`);
            await this.loadAgencies();
            await window.OptiStackApp.refreshActiveMap(false);
        }
    },
};

window.AgenciesCRUDModule = AgenciesCRUDModule;
