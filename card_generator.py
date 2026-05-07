"""卡密生成工具 — 用于批量生成各类卡密并存入数据库"""
import sys
from card_system import CARD_TYPES, generate_card_keys


def main():
    print("=" * 50)
    print("  卡密生成工具")
    print("=" * 50)
    print()
    print("卡密类型:")
    for key, info in CARD_TYPES.items():
        print(f"  {key}: {info['label']}")
    print()

    card_type = input("请输入卡密类型 (trial/monthly/quarterly/yearly/permanent): ").strip()
    if card_type not in CARD_TYPES:
        print(f"无效类型: {card_type}")
        sys.exit(1)

    try:
        count = int(input("请输入生成数量: ").strip())
    except ValueError:
        print("数量必须是整数")
        sys.exit(1)

    if count < 1 or count > 1000:
        print("数量范围: 1-1000")
        sys.exit(1)

    print()
    print(f"正在生成 {count} 张 {CARD_TYPES[card_type]['label']}...")
    keys = generate_card_keys(card_type, count)

    print()
    print("=" * 50)
    print(f"  已生成 {len(keys)} 张卡密:")
    print("=" * 50)
    for i, key in enumerate(keys, 1):
        print(f"  {i:3d}. {key}")
    print("=" * 50)
    print("卡密已存入数据库，可直接使用。")


if __name__ == '__main__':
    main()
