ekko后端部署指南

1.创建虚拟环境

```bash
conda create -n ekko-backend_env python=3.10 -y
```

2.安装依赖

```bash
pip install -r requirements.txt
```

3.启动指令

```bash
uvicorn main:ekko --reload
```
