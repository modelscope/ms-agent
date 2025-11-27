# Git配置指南

## Git用户配置

如果你在提交时遇到"empty ident name not allowed"错误，请按以下步骤配置Git用户信息：

### 1. 设置全局用户信息

```bash
# 设置用户名
git config --global user.name "Your Name"

# 设置邮箱
git config --global user.email "your.email@example.com"
```

### 2. 验证配置

```bash
# 检查用户名
git config --get user.name

# 检查邮箱
git config --get user.email
```

### 3. 如果仍然遇到问题

如果设置了用户信息后仍然遇到问题，尝试以下方法：

#### 方法1: 重新设置配置
```bash
# 删除旧的配置
git config --unset --global user.name
git config --unset --global user.email

# 重新设置
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

#### 方法2: 直接提交时指定作者
```bash
git commit --author="Your Name <your.email@example.com>" -m "Your commit message"
```

#### 方法3: 检查配置文件
检查你的`.gitconfig`文件是否正确：
```bash
cat ~/.gitconfig
```

应该包含类似以下内容：
```
[user]
    name = Your Name
    email = your.email@example.com
```

### 4. 配置验证命令

使用此命令验证你的Git配置是否正确：
```bash
git config --list | grep -E "user.(name|email)"
```

应该输出类似：
```
user.name=Your Name
user.email=your.email@example.com
```

### 5. 提交前的最终检查

在尝试提交之前，运行以下命令确认配置：
```bash
# 确认用户配置
git config user.name
git config user.email

# 查看当前仓库状态
git status
```

### 6. 提交更改

配置完成后，你可以正常提交：
```bash
# 添加文件到暂存区
git add .

# 提交更改
git commit -m "Your commit message"

# 推送到远程分支
git push origin feature/skx-pytest
```

### 7. 配置其他常用Git选项（可选）

```bash
# 设置默认编辑器
git config --global core.editor "vim"

# 设置默认分支名称
git config --global init.defaultBranch main

# 设置自动换行处理
git config --global core.autocrlf input
```