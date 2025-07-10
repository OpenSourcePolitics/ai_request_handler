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

## TODO 

* Add resources limits to pods
* Remove dummy resources in app request
* Defining HPA
