@{
    ClusterName           = "oncall-lab"
    KindConfig            = "kubernetes/kind-cluster.yaml"
    ManifestsDir          = "kubernetes"
    SecretEnvFile         = "kubernetes/secrets/payment-service.env"
    SecretEnvExample      = "kubernetes/secrets/payment-service.env.example"
    ServicesDir           = "sample-services"
    Dockerfile            = "docker/python-service.Dockerfile"
    ServiceEntrypoint     = "main.py"
    ServicePort           = 8080
    PartOfLabel           = "app.kubernetes.io/part-of=shop"
    Namespace             = "shop"
    RolloutTimeout        = "180s"
    SmokeTestService      = "order-service"
    SmokeTestLocalPort    = 18080
    SmokeTestServicePort  = 80
}
