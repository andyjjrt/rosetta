# Kubernetes

Rosetta supports automatic Lavalink node discovery via the Kubernetes Endpoints API. This is useful when running multiple Lavalink replicas behind a headless Service.

## Architecture

```
┌──────────────┐       ┌────────────────────────┐
│   Rosetta    │──────▶│  K8s Endpoints API     │
│   Pod        │       │  (auto-discovers nodes) │
└──────┬───────┘       └────────────────────────┘
       │
       ├──▶ lavalink-0 (10.0.1.10:2333)
       ├──▶ lavalink-1 (10.0.1.11:2333)
       └──▶ lavalink-2 (10.0.1.12:2333)
```

## Deploy Lavalink

Deploy Lavalink as a `StatefulSet` or `Deployment` with a **headless Service**:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: lavalink
spec:
  clusterIP: None
  selector:
    app: lavalink
  ports:
    - port: 2333
      targetPort: 2333
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: lavalink
spec:
  serviceName: lavalink
  replicas: 2
  selector:
    matchLabels:
      app: lavalink
  template:
    metadata:
      labels:
        app: lavalink
    spec:
      containers:
        - name: lavalink
          image: ghcr.io/lavalink-devs/lavalink:4.2.2-alpine
          ports:
            - containerPort: 2333
          env:
            - name: _JAVA_OPTIONS
              value: "-Xmx2G"
          volumeMounts:
            - name: config
              mountPath: /opt/Lavalink/application.yml
              subPath: application.yml
      volumes:
        - name: config
          configMap:
            name: lavalink-config
```

## Deploy Rosetta

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rosetta
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rosetta
  template:
    metadata:
      labels:
        app: rosetta
    spec:
      serviceAccountName: rosetta
      containers:
        - name: rosetta
          image: ghcr.io/andyjjrt/rosetta:latest
          env:
            - name: BOT_TOKEN
              valueFrom:
                secretKeyRef:
                  name: rosetta-secrets
                  key: bot-token
            - name: BOT_CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: rosetta-secrets
                  key: client-id
            - name: LAVALINK_DISCOVERY_MODE
              value: "k8s"
            - name: LAVALINK_K8S_NAMESPACE
              value: "default"
            - name: LAVALINK_K8S_SERVICE_NAME
              value: "lavalink"
            - name: LAVALINK_K8S_SERVICE_PORT
              value: "2333"
            - name: LAVALINK_PASSWORD
              value: "youshallnotpass"
          volumeMounts:
            - name: mygo-data
              mountPath: /app/mygo-ave-video
      volumes:
        - name: mygo-data
          persistentVolumeClaim:
            claimName: mygo-data
```

## RBAC

The Rosetta pod's service account needs permission to read Endpoints:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rosetta
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: rosetta-lavalink-reader
rules:
  - apiGroups: [""]
    resources: ["endpoints"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: rosetta-lavalink-reader
subjects:
  - kind: ServiceAccount
    name: rosetta
roleRef:
  kind: Role
  name: rosetta-lavalink-reader
  apiGroup: rbac.authorization.k8s.io
```

## How Discovery Works

When `LAVALINK_DISCOVERY_MODE=k8s`, Rosetta:

1. Uses the Kubernetes API to read Endpoints for the configured service
2. Extracts individual pod IPs from the endpoint subsets
3. Connects to each Lavalink pod as a separate lava_lyra node
4. Logs each discovered node with its pod name and IP

Note: `LAVALINK_LOCAL_NODE_COUNT` has no effect when `LAVALINK_DISCOVERY_MODE=k8s`. The number of nodes is determined by the discovered pod endpoints, not the local setting.

## Runtime Management

- **`!reload_nodes`** — Re-discover all Lavalink endpoints and reconnect (owner only)
- **`/switchnode`** — Move the current voice session to a different Lavalink node
