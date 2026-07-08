export const STORY_CAPACITY = Object.freeze({
  chapterMin: 1,
  chapterMax: 20,
  defaultChapterCount: 5,
  sceneMin: 1,
  sceneMax: 20,
  defaultSceneCount: 5,
});

export function rangeOptions(min, max) {
  const start = Number(min) || 1;
  const end = Math.max(start, Number(max) || start);
  return Array.from({ length: end - start + 1 }, (_, index) => start + index);
}

export const CHAPTER_COUNT_OPTIONS = rangeOptions(
  STORY_CAPACITY.chapterMin,
  STORY_CAPACITY.chapterMax,
);

export const SCENE_COUNT_OPTIONS = rangeOptions(
  STORY_CAPACITY.sceneMin,
  STORY_CAPACITY.sceneMax,
);

export function defaultChapterCount(value) {
  return Number(value) || STORY_CAPACITY.defaultChapterCount;
}

export function defaultSceneCount(value) {
  return Number(value) || STORY_CAPACITY.defaultSceneCount;
}
