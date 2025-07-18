# AI Request Handler

## App Flask Webserver


### Generate BasicAuth

1. Generate HTPASSWD
```
   htpasswd -c auth <USERNAME> 
```
2. Create secret
```
kubectl create secret generic basic-auth --from-file=auth -n decidim-ai
```

3. Appy ingress
```
kubectl apply -f ingress.yaml
```

source: https://kubernetes.github.io/ingress-nginx/examples/auth/basic/

## 📦 Versioning and Deployment

### Prerequisites

* You must be on the `main` branch.
* Ensure the `release.sh` script is executable and located at the root of your repository.
* Your GitHub Actions workflow `build_and_push_image.yml` must be configured to trigger on tags matching `v*.*.*`.
* Define the following in **Settings → Environments → Repository Variables** and **Secrets**:

  * `REGISTRY_ENDPOINT` (e.g. `rg.fr-par.scw.cloud`)
  * `REGISTRY_NAMESPACE` (e.g. `decidim-ai`)
  * `IMAGE_NAME` (e.g. `ai_request_handler`)
  * `TOKEN` (registry authentication token)

---

### 1. Create a New Release

1. **Switch to `main` and pull latest**

   ```bash
   git checkout main
   git pull origin main
   ```

2. **Run the release script**

   ```bash
   chmod +x release.sh
   ./release.sh
   ```

   * You’ll be prompted to enter the new tag (e.g. `1.2.3`).
   * The script will:

     1. Update `gitops/flux-sync.yaml` to `newTag: v1.2.3`
     2. Update `deployment.yaml` to use image `…/ai_request_handler:v1.2.3`
     3. Commit both changes and create a Git tag `v1.2.3`
     4. Push `main` and the new tag to the remote

3. **Verify the tag was created**

   ```bash
   git tag --list | grep v1.2.3
   ```

---

### 2. Flux Deployment

* Once the image is available, Flux (via `gitops/flux-sync.yaml`) notices the updated `newTag` and automatically rolls out the new version in the `decidim-ai` namespace.
* To check rollout status:

  ```bash
  kubectl -n decidim-ai rollout status deployment/ai-request-handler-deploy
  ```

---

