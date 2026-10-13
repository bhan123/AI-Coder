import { _decorator, Component, instantiate, JsonAsset, Node, Prefab, Vec3, resources } from 'cc';
import { AudioManager } from '../core/AudioManager';
import { Board } from './Board';
import { Tile, TileSpecial } from './Tile';
import { MatchSystem } from './MatchSystem';
import { PropSystem } from './PropSystem';

const { ccclass, property } = _decorator;

export interface LevelJson {
    levelId: number;
    slotCapacity: number;
    cellWidth: number;
    cellHeight: number;
    layerOffset: number;
    origin: { x: number; y: number };
    tiles: Array<{
        pattern: number;
        gx: number;
        gy: number;
        gz: number;
        special?: TileSpecial;
    }>;
}

/**
 * 关卡管理器：
 * - 加载 resources/levels/level_xxx.json
 * - 实例化所有牌到 Board
 * - 同时构造 MatchSystem 与 PropSystem，外部通过 .matchSystem / .propSystem 访问
 *
 * 用法（在 GameScene 里）：
 *   const lm = this.node.addComponent(LevelManager);
 *   lm.loadLevel(1);
 */
@ccclass('LevelManager')
export class LevelManager extends Component {
    @property(Board)
    public board: Board | null = null;

    @property(Prefab)
    public tilePrefab: Prefab | null = null;

    @property(Node)
    public tileContainer: Node | null = null;

    public matchSystem: MatchSystem | null = null;
    public propSystem: PropSystem | null = null;

    /** 当前关卡的几何参数（供 PropSystem.shuffle 用） */
    private geo = {
        origin: new Vec3(0, 0, 0),
        cellWidth: 80,
        cellHeight: 80,
        layerOffset: 30,
    };

    /** 加载并构建一关 */
    async loadLevel(levelId: number) {
        const json = await this.fetchLevelJson(levelId);
        if (!json) {
            console.error(`[LevelManager] level ${levelId} not found`);
            return;
        }
        this.buildLevel(json);
    }

    private async fetchLevelJson(levelId: number): Promise<LevelJson | null> {
        const path = `levels/level_${String(levelId).padStart(3, '0')}`;
        return new Promise((resolve) => {
            resources.load(path, JsonAsset, (err, asset) => {
                if (err || !asset) return resolve(null);
                resolve(asset.json as LevelJson);
            });
        });
    }

    private buildLevel(json: LevelJson) {
        if (!this.board || !this.tilePrefab || !this.tileContainer) {
            console.error('[LevelManager] missing dependencies');
            return;
        }

        // 关卡校验（warn-only，不阻塞）
        this.validateLevel(json);

        // 清理上一关残留
        this.tileContainer.removeAllChildren();

        // 关卡几何参数
        this.geo = {
            origin: new Vec3(json.origin.x, json.origin.y, 0),
            cellWidth: json.cellWidth,
            cellHeight: json.cellHeight,
            layerOffset: json.layerOffset,
        };

        // 初始化 MatchSystem / PropSystem
        this.matchSystem = new MatchSystem(this.board, { slotCapacity: json.slotCapacity });
        this.propSystem = new PropSystem(this.board, this.matchSystem, this.geo);

        const origin = this.geo.origin;

        for (let i = 0; i < json.tiles.length; i++) {
            const td = json.tiles[i];
            const node = this.spawnTileNode(i);
            const worldPos = this.board.gridToWorld(td.gx, td.gy, td.gz, origin, json.cellWidth, json.cellHeight, json.layerOffset);
            node.setPosition(worldPos);
            (node as any).originalPos = worldPos.clone();

            this.board.addTile({
                id: i,
                pattern: td.pattern,
                gx: td.gx,
                gy: td.gy,
                gz: td.gz,
                node,
                special: td.special ?? 'none',
            });
        }
    }

    /** 关卡 JSON 校验：仅 warn，不阻塞 */
    private validateLevel(json: LevelJson) {
        // 关卡 id 必须等于文件名中的数字
        if (json.levelId !== Number(json.levelId) || json.levelId < 1) {
            console.warn(`[LevelManager] levelId 异常: ${json.levelId}`);
        }
        // tiles.length 是否 3 的倍数
        if (json.tiles.length % 3 !== 0) {
            console.warn(`[LevelManager] tiles.length=${json.tiles.length} 不是 3 的倍数`);
        }
        // 每个 pattern 的 normal 牌数是否是 3 的倍数
        const counts = new Map<number, number>();
        let bomb = 0;
        let wild = 0;
        for (const t of json.tiles) {
            if (t.special === 'bomb') bomb += 1;
            else if (t.special === 'wild') wild += 1;
            else {
                counts.set(t.pattern, (counts.get(t.pattern) ?? 0) + 1);
            }
        }
        for (const [p, c] of counts) {
            if (c % 3 !== 0) {
                console.warn(`[LevelManager] pattern ${p} 有 ${c} 张 normal 牌，不是 3 的倍数`);
            }
        }
        // 任何特殊牌都不参与 slot 消除判定中的 pattern 计数；提示玩家避免数量失衡
        if (bomb > 0 && wild > 0) {
            console.warn(`[LevelManager] 同时存在 bomb 和 wild，可能导致消除判定复杂化`);
        }
    }

    /** 卸载当前关卡：清空 tileContainer + 释放池 + 重置 slot */
    unloadLevel() {
        if (this.tileContainer) {
            this.tileContainer.removeAllChildren();
        }
        if (this.board) {
            // 重置 Board 内部 grid + tilePool
            (this.board as any).grid = new Map<string, any>();
            (this.board as any).maxZ = 0;
            if ((this.board as any).tilePool) {
                (this.board as any).tilePool.length = 0;
            }
        }
        if (this.matchSystem) {
            this.matchSystem.reset();
        }
        this.matchSystem = null;
        this.propSystem = null;
    }

    private spawnTileNode(id: number): Node {
        // 这里直接 instantiate 预制体，简化处理
        // 实际项目建议做对象池，避免频繁 instantiate
        const node = this.tilePrefab
            ? instantiate(this.tilePrefab)
            : new Node(`Tile_${id}`);
        node.setParent(this.tileContainer);
        const tileComp = node.getComponent(Tile) ?? node.addComponent(Tile);
        return node;
    }
}