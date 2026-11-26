/**
 * Motor de Visualización 3D Interactivo - OptiStack HMI (Three.js WebGL)
 * Renderiza el contenedor con las dimensiones personalizadas del furgón (L, A, H),
 * ubica dinámicamente los paquetes en (CoordX, CoordY, CoordZ), dibuja el Centro
 * de Gravedad (CoG) y soporta Raycasting, Corte Longitudinal y Scrubber Paso a Paso.
 */

class StowageViewer3D {
    constructor(containerElementId, onPackageSelectCallback) {
        this.container = document.getElementById(containerElementId);
        this.onPackageSelect = onPackageSelectCallback;

        this.containerDims = { L: 680, W: 245, H: 250 };
        this.packages = [];
        this.packageMeshes = new Map(); // PackageID -> THREE.Group
        this.selectedPackageId = null;

        // Opciones de visualización interactiva
        this.colorMode = "agency"; // 'agency' | 'weight' | 'sequence'
        this.xrayEnabled = false;
        this.sliceXPercent = 100;
        this.maxSequenceVisible = Infinity;
        this.activeAgencyFilter = null;

        this._initScene();
        this._initLights();
        this._buildContainerGeometry(this.containerDims.L, this.containerDims.W, this.containerDims.H);
        this._initInteraction();
        this._animate();
    }

    _initScene() {
        const width = this.container.clientWidth || 900;
        const height = this.container.clientHeight || 600;

        this.scene = new THREE.Scene();

        this.camera = new THREE.PerspectiveCamera(42, width / height, 5, 12000);
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.shadowMap.enabled = true;

        this.container.innerHTML = "";
        this.container.appendChild(this.renderer.domElement);

        this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.07;
        this.controls.maxDistance = 4500;
        this.controls.minDistance = 120;

        this.containerGroup = new THREE.Group();
        this.packagesGroup = new THREE.Group();
        this.cogMarkerGroup = new THREE.Group();

        this.scene.add(this.containerGroup);
        this.scene.add(this.packagesGroup);
        this.scene.add(this.cogMarkerGroup);

        window.addEventListener("resize", () => this.handleResize());
    }

    _initLights() {
        const ambient = new THREE.AmbientLight(0xdbeafe, 0.72);
        this.scene.add(ambient);

        const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.68);
        dirLight1.position.set(900, 1400, 1000);
        this.scene.add(dirLight1);

        const dirLight2 = new THREE.DirectionalLight(0x38bdf8, 0.28);
        dirLight2.position.set(-800, 600, -700);
        this.scene.add(dirLight2);
    }

    handleResize() {
        if (!this.container) return;
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;
        if (w <= 0 || h <= 0) return;
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h);
    }

    /**
     * Reconstruye la geometría 3D del furgón cuando cambia el camión activo.
     * Origen (0,0,0) del sistema de coordenadas de estiba:
     *   X: 0 (Cabina/Fondo) -> L (Puerta trasera)
     *   Y: 0 (Piso)         -> H (Techo)
     *   Z: 0 (Pared Izq)    -> W (Pared Der)
     */
    _buildContainerGeometry(L, W, H) {
        this.containerDims = { L, W, H };

        while (this.containerGroup.children.length > 0) {
            this.containerGroup.remove(this.containerGroup.children[0]);
        }

        // Centrar el furgón en torno al origen del mundo 3D para rotación orbital cómoda
        this.offset = { x: -L / 2, y: -H / 3, z: -W / 2 };
        this.containerGroup.position.set(this.offset.x, this.offset.y, this.offset.z);
        this.packagesGroup.position.set(this.offset.x, this.offset.y, this.offset.z);
        this.cogMarkerGroup.position.set(this.offset.x, this.offset.y, this.offset.z);

        // 1. Plataforma / Piso del Furgón
        const floorGeo = new THREE.BoxGeometry(L, 4, W);
        const floorMat = new THREE.MeshStandardMaterial({
            color: 0x0f172a,
            roughness: 0.75,
            metalness: 0.25,
        });
        const floorMesh = new THREE.Mesh(floorGeo, floorMat);
        floorMesh.position.set(L / 2, -2, W / 2);
        this.containerGroup.add(floorMesh);

        // 2. Grilla métrica sobre el piso (cada ~50 cm)
        const gridLinesMat = new THREE.LineBasicMaterial({
            color: 0x334155,
            transparent: true,
            opacity: 0.65,
        });
        const gridPoints = [];
        const stepCm = 50;
        for (let x = 0; x <= L; x += stepCm) {
            gridPoints.push(new THREE.Vector3(x, 0.3, 0));
            gridPoints.push(new THREE.Vector3(x, 0.3, W));
        }
        for (let z = 0; z <= W; z += stepCm) {
            gridPoints.push(new THREE.Vector3(0, 0.3, z));
            gridPoints.push(new THREE.Vector3(L, 0.3, z));
        }
        const gridGeo = new THREE.BufferGeometry().setFromPoints(gridPoints);
        this.containerGroup.add(new THREE.LineSegments(gridGeo, gridLinesMat));

        // 3. Estructura de Alambre (Wireframe) del Contenedor Personalizado
        const boxGeo = new THREE.BoxGeometry(L, H, W);
        const edgesGeo = new THREE.EdgesGeometry(boxGeo);
        const edgesMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 2 });
        const wireframe = new THREE.LineSegments(edgesGeo, edgesMat);
        wireframe.position.set(L / 2, H / 2, W / 2);
        this.containerGroup.add(wireframe);

        // 4. Pared Frontal (Fondo hacia la Cabina en X = 0) semitransparente
        const frontWallGeo = new THREE.PlaneGeometry(W, H);
        const frontWallMat = new THREE.MeshBasicMaterial({
            color: 0x0284c7,
            transparent: true,
            opacity: 0.14,
            side: THREE.DoubleSide,
        });
        const frontWall = new THREE.Mesh(frontWallGeo, frontWallMat);
        frontWall.rotation.y = Math.PI / 2;
        frontWall.position.set(0, H / 2, W / 2);
        this.containerGroup.add(frontWall);

        // 5. Marco de Puerta Trasera (en X = L) con color ámbar indicador de ingreso IoT
        const doorFrameGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(2, H, W));
        const doorFrameMat = new THREE.LineBasicMaterial({ color: 0xf59e0b });
        const doorFrame = new THREE.LineSegments(doorFrameGeo, doorFrameMat);
        doorFrame.position.set(L, H / 2, W / 2);
        this.containerGroup.add(doorFrame);

        this.setCameraPreset("iso");
    }

    /**
     * Cambia la vista de la cámara a una posición ergonómica predefinida.
     */
    setCameraPreset(preset) {
        const { L, W, H } = this.containerDims;
        const maxDim = Math.max(L, W, H);
        this.controls.target.set(0, H * 0.15, 0);

        if (preset === "top") {
            this.camera.position.set(0, maxDim * 1.65, 1);
        } else if (preset === "side") {
            this.camera.position.set(0, H * 0.25, maxDim * 1.45);
        } else if (preset === "rear") {
            this.camera.position.set(maxDim * 1.35, H * 0.35, 0);
        } else {
            // Isométrica por defecto
            this.camera.position.set(maxDim * 0.95, maxDim * 0.78, maxDim * 1.05);
        }
        this.controls.update();
    }

    /**
     * Sincroniza el estado completo del Mapa de Estiba y sus paquetes 3D.
     */
    updateStowageData(stowageMapData, animateLatest = false) {
        const { LengthCm, WidthCm, HeightCm, packages, kpis } = stowageMapData;

        if (
            LengthCm !== this.containerDims.L ||
            WidthCm !== this.containerDims.W ||
            HeightCm !== this.containerDims.H
        ) {
            this._buildContainerGeometry(LengthCm, WidthCm, HeightCm);
        }

        this.packages = packages || [];
        this._rebuildPackagesMeshes(animateLatest);
        if (kpis) {
            this._updateCoGMarker(kpis.cog_x_cm, kpis.cog_y_cm, kpis.cog_z_cm, kpis.stability_status);
        }
    }

    _getPackageColor(pkg, totalCount) {
        if (this.colorMode === "weight") {
            // Mapa de calor: azul (ligero) -> ámbar (medio) -> rojo (pesado >= 45kg)
            const ratio = Math.min(1, Math.max(0, (pkg.WeightKg - 5) / 45));
            const color = new THREE.Color();
            color.setHSL((1 - ratio) * 0.58, 0.85, 0.5);
            return color;
        }
        if (this.colorMode === "sequence") {
            const ratio = totalCount > 1 ? (pkg.SequenceOrder - 1) / (totalCount - 1) : 0;
            const color = new THREE.Color();
            color.setHSL(0.55 - ratio * 0.42, 0.82, 0.52);
            return color;
        }
        return new THREE.Color(pkg.ColorHex || "#38bdf8");
    }

    _rebuildPackagesMeshes(animateLatest = false) {
        while (this.packagesGroup.children.length > 0) {
            this.packagesGroup.remove(this.packagesGroup.children[0]);
        }
        this.packageMeshes.clear();

        const total = this.packages.length;
        const latestPkgId = total > 0 ? this.packages[total - 1].PackageID : null;

        this.packages.forEach((pkg) => {
            const lx = pkg.PlacedLengthCm;
            const ly = pkg.PlacedHeightCm;
            const lz = pkg.PlacedWidthCm;

            const group = new THREE.Group();
            group.userData = { packageData: pkg };

            const boxGeo = new THREE.BoxGeometry(lx, ly, lz);
            const baseColor = this._getPackageColor(pkg, total);

            const isLatest = pkg.PackageID === latestPkgId;
            const isSelected = pkg.PackageID === this.selectedPackageId;

            const boxMat = new THREE.MeshStandardMaterial({
                color: baseColor,
                roughness: 0.42,
                metalness: 0.12,
                transparent: true,
                opacity: this.xrayEnabled ? 0.32 : 0.92,
            });

            const mesh = new THREE.Mesh(boxGeo, boxMat);
            mesh.userData = { packageData: pkg };
            group.add(mesh);

            // Contorno de aristas nítidas para distinguir cada bulto
            const edgesGeo = new THREE.EdgesGeometry(boxGeo);
            const edgeColor = isSelected ? 0xffffff : isLatest ? 0x38bdf8 : 0x0f172a;
            const edgesMat = new THREE.LineBasicMaterial({
                color: edgeColor,
                linewidth: isSelected || isLatest ? 2.5 : 1,
            });
            const edges = new THREE.LineSegments(edgesGeo, edgesMat);
            group.add(edges);

            // Coordenadas del centro de la caja en Three.js
            const targetX = pkg.CoordX + lx / 2;
            const targetY = pkg.CoordY + ly / 2;
            const targetZ = pkg.CoordZ + lz / 2;

            if (animateLatest && isLatest) {
                // Iniciar en la puerta trasera y deslizar suavemente hacia su coordenada (x,y,z)
                group.position.set(this.containerDims.L + lx * 0.5, targetY + 25, targetZ);
                group.userData.targetPos = new THREE.Vector3(targetX, targetY, targetZ);
                group.userData.animating = true;
            } else {
                group.position.set(targetX, targetY, targetZ);
                group.userData.animating = false;
            }

            this.packagesGroup.add(group);
            this.packageMeshes.set(pkg.PackageID, group);
        });

        this.applyVisibilityFilters();
    }

    /**
     * Aplica en tiempo real el Corte Longitudinal (Eje X), el Scrubber Paso a Paso
     * y el filtro por Ruta/Agencia sin reconstruir la geometría.
     */
    applyVisibilityFilters() {
        const maxX = (this.sliceXPercent / 100.0) * this.containerDims.L;

        this.packageMeshes.forEach((group) => {
            const pkg = group.userData.packageData;
            const withinSliceX = pkg.CoordX + pkg.PlacedLengthCm * 0.5 <= maxX + 0.5;
            const withinStep = pkg.SequenceOrder <= this.maxSequenceVisible;
            const matchesAgency = !this.activeAgencyFilter || pkg.TargetAgencyID === this.activeAgencyFilter;

            group.visible = withinSliceX && withinStep && matchesAgency;

            const mesh = group.children[0];
            if (mesh && mesh.material) {
                const isSelected = pkg.PackageID === this.selectedPackageId;
                mesh.material.opacity = isSelected ? 1.0 : this.xrayEnabled ? 0.28 : 0.93;
                mesh.material.emissive = new THREE.Color(isSelected ? 0x1e3a8a : 0x000000);
            }
        });
    }

    _updateCoGMarker(cogX, cogY, cogZ, stabilityStatus) {
        while (this.cogMarkerGroup.children.length > 0) {
            this.cogMarkerGroup.remove(this.cogMarkerGroup.children[0]);
        }
        if (this.packages.length === 0) return;

        const colorHex =
            stabilityStatus === "CRITICAL"
                ? 0xef4444
                : stabilityStatus === "WARNING"
                ? 0xf59e0b
                : 0x10b981;

        const sphereGeo = new THREE.SphereGeometry(9, 20, 20);
        const sphereMat = new THREE.MeshBasicMaterial({ color: colorHex });
        const sphere = new THREE.Mesh(sphereGeo, sphereMat);
        sphere.position.set(cogX, Math.max(8, cogY), cogZ);
        this.cogMarkerGroup.add(sphere);

        // Línea de plomada hacia el piso para visualizar el balance sobre los ejes
        const linePoints = [
            new THREE.Vector3(cogX, Math.max(8, cogY), cogZ),
            new THREE.Vector3(cogX, 0.5, cogZ),
        ];
        const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints);
        const lineMat = new THREE.LineBasicMaterial({ color: colorHex });
        this.cogMarkerGroup.add(new THREE.Line(lineGeo, lineMat));
    }

    selectPackageById(packageId) {
        this.selectedPackageId = packageId;
        this._rebuildPackagesMeshes(false);
        const pkg = this.packages.find((p) => p.PackageID === packageId) || null;
        if (this.onPackageSelect) {
            this.onPackageSelect(pkg);
        }
    }

    _initInteraction() {
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();

        let pointerDownPos = { x: 0, y: 0 };
        this.renderer.domElement.addEventListener("pointerdown", (e) => {
            pointerDownPos = { x: e.clientX, y: e.clientY };
        });

        this.renderer.domElement.addEventListener("pointerup", (e) => {
            const dist = Math.hypot(e.clientX - pointerDownPos.x, e.clientY - pointerDownPos.y);
            if (dist > 6) return; // Fue un giro de cámara con OrbitControls

            const rect = this.renderer.domElement.getBoundingClientRect();
            this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
            this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

            this.raycaster.setFromCamera(this.mouse, this.camera);
            const selectableMeshes = [];
            this.packageMeshes.forEach((group) => {
                if (group.visible && group.children[0]) {
                    selectableMeshes.push(group.children[0]);
                }
            });

            const intersects = this.raycaster.intersectObjects(selectableMeshes, false);
            if (intersects.length > 0) {
                const hitPkg = intersects[0].object.userData.packageData;
                if (hitPkg) {
                    this.selectPackageById(hitPkg.PackageID);
                }
            } else {
                this.selectPackageById(null);
            }
        });
    }

    _animate() {
        requestAnimationFrame(() => this._animate());

        // Animar inserción suave de paquetes entrantes
        this.packageMeshes.forEach((group) => {
            if (group.userData.animating && group.userData.targetPos) {
                group.position.lerp(group.userData.targetPos, 0.16);
                if (group.position.distanceTo(group.userData.targetPos) < 0.4) {
                    group.position.copy(group.userData.targetPos);
                    group.userData.animating = false;
                }
            }
        });

        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }
}

window.StowageViewer3D = StowageViewer3D;
