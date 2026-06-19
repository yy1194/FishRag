# CentOS 7.9 域名部署

本文件面向 CentOS 7.9、4C / 8G / 30G 的单机演示部署。当前方案使用 Docker Compose 启动 FishRag，再由宿主机 Nginx 统一反向代理到域名。

CentOS 7.9 已停止常规维护，建议将该方案定位为演示或测试环境。正式生产环境建议迁移到 Rocky Linux 9、AlmaLinux 9 或 CentOS Stream 9，并将磁盘扩容到 80G 以上。

## 部署架构

```text
用户浏览器
  |
  | https://rag.example.com
  v
宿主机 Nginx :80/:443
  |-- /api/  -> 127.0.0.1:8000  -> fishrag-api
  |-- /      -> 127.0.0.1:5173  -> fishrag-web

Docker Compose 内部：
api -> postgres / redis / opensearch
prometheus -> api / metrics
grafana -> prometheus
```

建议公网只开放：

| 端口 | 用途 |
| --- | --- |
| `22` | SSH，仅允许可信 IP 更好 |
| `80` | HTTP，给 Let's Encrypt 签发证书和跳转 HTTPS |
| `443` | HTTPS，正式访问入口 |

不要向公网开放 `5432`、`6379`、`9200`、`9600`、`9090`、`3000`、`8000`、`5173`。

## 1. DNS 解析

在域名服务商控制台添加 A 记录：

```text
主机记录: rag
记录类型: A
记录值: 你的服务器公网 IP
```

生效后在本机或服务器验证：

```bash
dig rag.example.com +short
```

如果服务器没有 `dig`：

```bash
nslookup rag.example.com
```

## 2. 检查 Docker 环境

你已经有 Docker 环境，先确认版本和 Compose 插件：

```bash
docker version
docker compose version
docker run --rm hello-world
```

如果 `docker compose` 不存在，需要安装 Docker Compose plugin。CentOS 7.9 上仍可使用 Docker 的 CentOS 仓库，但这是兼容路径，后续维护风险高。

## 3. 配置系统参数

OpenSearch 需要 `vm.max_map_count`：

```bash
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf
sudo sysctl --system
cat /proc/sys/vm/max_map_count
```

30G 磁盘偏紧，建议限制 Docker 日志：

```bash
sudo mkdir -p /etc/docker

sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  }
}
EOF

sudo systemctl restart docker
```

查看 Docker 磁盘占用：

```bash
docker system df
du -sh /var/lib/docker 2>/dev/null || true
```

## 4. 拉取项目

```bash
sudo mkdir -p /opt/fishrag
sudo chown -R $USER:$USER /opt/fishrag

git clone <你的仓库地址> /opt/fishrag
cd /opt/fishrag
```

如果服务器不能直接访问 Git 仓库，可以在本地打包后上传：

```bash
tar --exclude=.git --exclude=apps/web/node_modules --exclude=apps/web/dist -czf fishrag.tar.gz FishRag
scp fishrag.tar.gz user@服务器IP:/opt/
```

服务器上解压：

```bash
cd /opt
tar -xzf fishrag.tar.gz
mv FishRag fishrag
cd /opt/fishrag
```

## 5. 配置环境变量

```bash
cp .env.example .env
vim .env
```

将域名替换成你的真实域名：

```env
FISHRAG_ENV=production
FISHRAG_JWT_SECRET_KEY=请换成强随机字符串

FISHRAG_API_PORT=127.0.0.1:8000
FISHRAG_WEB_PORT=127.0.0.1:5173
POSTGRES_PORT=127.0.0.1:5432
REDIS_PORT=127.0.0.1:6379
OPENSEARCH_PORT=127.0.0.1:9200
PROMETHEUS_PORT=127.0.0.1:9090
GRAFANA_PORT=127.0.0.1:3000

VITE_API_BASE_URL=https://rag.example.com/api/v1
FISHRAG_CORS_ORIGINS=https://rag.example.com

FISHRAG_LLM_API_KEY=你的 DeepSeek Key
FISHRAG_EMBEDDING_API_KEY=你的 SiliconFlow Key
FISHRAG_RERANKER_API_KEY=你的 SiliconFlow Key

GRAFANA_ADMIN_PASSWORD=请换成强密码
```

当前 `docker-compose.yml` 中 API 容器内部数据库连接被覆盖为：

```text
postgresql+asyncpg://fishrag:fishrag@postgres:5432/fishrag
```

因此第一次部署先不要改 `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`。后续需要正式生产化时，应把 Compose 内部连接也改为变量化。

注意：OpenSearch 的 `9600` 端口当前在 `docker-compose.yml` 中固定为 `9600:9600`。如果服务器安全组或防火墙已经只开放 `80/443`，公网访问不到它；如果想进一步收紧，可将该行改成：

```yaml
- "127.0.0.1:9600:9600"
```

## 6. 启动 FishRag

首次构建可能较慢：

```bash
docker compose --profile app build api web --progress plain
docker compose --profile app up -d
```

执行数据库迁移：

```bash
docker compose --profile app exec -T api alembic upgrade head
```

查看状态：

```bash
docker compose --profile app ps
docker compose --profile app logs --tail 100 api
```

本机回环验收：

```bash
python3 tools/acceptance_smoke.py --base-url http://127.0.0.1:8000/api/v1
```

预期：

```text
summary: 3/3 passed
```

## 7. 安装并配置 Nginx

```bash
sudo yum install -y epel-release
sudo yum install -y nginx
sudo systemctl enable --now nginx
```

创建站点配置：

```bash
sudo vim /etc/nginx/conf.d/fishrag.conf
```

写入以下内容，并替换域名：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name rag.example.com;

    client_max_body_size 60m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 300s;
    }

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

验证 HTTP：

```bash
curl -I http://rag.example.com
curl http://rag.example.com/api/v1/health
```

## 8. 开放防火墙

如果服务器启用了 `firewalld`：

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

云服务器还需要在云厂商安全组中开放：

```text
TCP 80
TCP 443
```

不要在安全组中开放数据库、Redis、OpenSearch、Prometheus、Grafana 和 API/Web 内部端口。

## 9. 申请 HTTPS 证书

Certbot 官方推荐使用 snap 安装。CentOS 7.9 上先安装 snapd：

```bash
sudo yum install -y epel-release
sudo yum install -y snapd
sudo systemctl enable --now snapd.socket
sudo ln -s /var/lib/snapd/snap /snap 2>/dev/null || true
```

安装 Certbot：

```bash
sudo snap install core
sudo snap refresh core
sudo yum remove -y certbot python2-certbot-nginx python3-certbot-nginx 2>/dev/null || true
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot
```

申请并自动改写 Nginx：

```bash
sudo certbot --nginx -d rag.example.com
```

测试续期：

```bash
sudo certbot renew --dry-run
```

如果 snap 在 CentOS 7.9 上不可用，可以改用 DNS 验证或 Docker 版 Certbot。优先保证 `http://rag.example.com` 已经能访问，再申请证书会少很多弯路。

## 10. HTTPS 验收

浏览器访问：

```text
https://rag.example.com
```

命令行验收：

```bash
curl https://rag.example.com/api/v1/health
python3 tools/acceptance_smoke.py --base-url https://rag.example.com/api/v1
```

如果验收失败：

- `502 Bad Gateway`：检查 `docker compose --profile app ps`，确认 `api` 和 `web` 正常运行。
- `404`：检查 Nginx 的 `location /api/` 是否把原始路径转发给了 `127.0.0.1:8000`。
- CORS 错误：检查 `.env` 中 `FISHRAG_CORS_ORIGINS=https://rag.example.com`，修改后需要重新创建 API 容器。
- 前端仍请求 `localhost`：检查 `.env` 中 `VITE_API_BASE_URL`，修改后需要重新构建 Web 镜像。

重新构建并启动：

```bash
docker compose --profile app build web --progress plain
docker compose --profile app up -d web api
```

## 11. 日常运维

查看服务：

```bash
docker compose --profile app ps
```

查看 API 日志：

```bash
docker compose --profile app logs -f api
```

更新代码并重启：

```bash
cd /opt/fishrag
git pull
docker compose --profile app build api web --progress plain
docker compose --profile app up -d
docker compose --profile app exec -T api alembic upgrade head
python3 tools/acceptance_smoke.py --base-url https://rag.example.com/api/v1
```

数据库备份：

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U fishrag fishrag > backups/fishrag-$(date +%F).sql
```

上传文件备份：

```bash
tar -czf backups/fishrag-storage-$(date +%F).tar.gz storage
```

磁盘检查：

```bash
df -h
docker system df
du -sh storage /var/lib/docker 2>/dev/null || true
```

30G 磁盘不要随意执行带 `--volumes` 的 Docker 清理命令，否则可能删除 PostgreSQL、OpenSearch 等数据卷。

## 12. 推荐后续改造

- 将 `POSTGRES_PASSWORD` 和 API 内部 `FISHRAG_DATABASE_URL` 完全变量化。
- 将 Compose 的内部服务端口默认绑定到 `127.0.0.1`。
- 为 Grafana 单独加 Basic Auth、VPN 或只允许内网访问。
- 将 PostgreSQL、OpenSearch 数据目录迁移到更大的独立磁盘。
- 正式生产环境迁移到受支持的 Linux 发行版。
