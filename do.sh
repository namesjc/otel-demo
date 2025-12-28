# 连续访问 50 次，产生一些数据
for i in {1..100}; do curl http://localhost:5000/buy; echo ""; done
