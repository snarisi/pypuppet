import json

from .exceptions import BrowserError


class JSObject:
    '''An interface for interacting with javascript objects in browser runtime'''

    def __init__(self, object_id, description, page):
        self._object_id = object_id
        self._description = description
        self._page = page

    def __repr__(self):
        return f'<{self.__class__.__name__} {self._description}>'

    def _method(self, method, *args):
        function = f'(element, ...args) => element.{method}(...args)'
        args = [self, *args]
        return self._remote_call(function, args)

    def _prop(self, prop):
        function = f'(element) => element.{prop}'
        args = [self]
        return self._remote_call(function, args)

    def _remote_call(self, function, args):
        # I think this is right, but having trouble figuring out exactly what all these IDs mean
        args = self._convert_args(args)
        execution_context_id = json.loads(self._object_id)['injectedScriptId']
        response = self._page.session.send(
            'Runtime.callFunctionOn',
            functionDeclaration=function,
            arguments=args,
            executionContextId=execution_context_id
        )

        # If the result is a primitive value return that
        if 'value' in response['result']:
            return response['result']['value']
        # Or return an Element if it's a DOM node, or a generic object
        # TODO: Is there a smarter way to retun different types of objects?
        elif response['result']['type'] == 'object':
            if response['result'].get('subtype') == 'node':
                return Element(response['result']['objectId'], response['result']['description'], self._page)
            else:
                return JSObject(response['result']['objectId'], response['result']['description'], self._page)
        elif response['result']['type'] == 'undefined':
            return None
        else:
            raise BrowserError('Unknown response from remote javascipt call')  # TODO: Find out if this can happen

    def _convert_args(self, args):
        to_return = []
        for arg in args:
            if hasattr(arg, '_object_id'):
                to_return.append({'objectId': arg._object_id})
            else:
                to_return.append({'value': arg})
        return to_return


class Element(JSObject):
    '''A special kind of JSObject with extra helper methods'''

    ORDERED_NODE_SNAPSHOT_TYPE = 7  # TODO: can get this code from JS?

    def xpath(self, expression):
        xpath_result = self._page.document._method('evaluate', expression, self, None, self.ORDERED_NODE_SNAPSHOT_TYPE)
        element_count = xpath_result._prop('snapshotLength')
        results = []
        for i in range(element_count):
            results.append(xpath_result._method('snapshotItem', i))
        return results

    def querySelector(self, selector):
        return self._method('querySelector', selector)

    def querySelectorAll(self, selector):
        query_selector_all_result = self._method('querySelectorAll', selector)
        length = query_selector_all_result._prop('length')
        results = []
        for i in range(length):
            results.append(query_selector_all_result._method('item', i))
        return results

    @property
    def html(self):
        return self._prop('outerHTML')

    @property
    def text(self):
        return self._prop('textContent')

    def focus(self):
        return self._method('focus')

    def click(self):
        quads = self._page.session.send('DOM.getContentQuads', objectId=self._object_id)['quads'][0]
        mean_x = sum([quads[i] for i in range(0, len(quads), 2)]) / (len(quads) / 2)
        mean_y = sum([quads[i] for i in range(1, len(quads), 2)]) / (len(quads) / 2)
        # TODO: Move the mouse in natural steps
        self._page.session.send('Input.dispatchMouseEvent', type='mouseMoved', x=mean_x, y=mean_y)
        self._page.session.send('Input.dispatchMouseEvent', type='mousePressed', x=mean_x, y=mean_y, button='left', clickCount=1)
        self._page.session.send('Input.dispatchMouseEvent', type='mouseReleased', x=mean_x, y=mean_y, button='left', clickCount=1)

    @property
    def is_visible(self):
        style = self._remote_call('window.getComputedStyle', [self])
        visibility = style._prop('visibility')
        has_visible_bounding_box = self._remote_call(
            '''
            (element) => {
                const rect = element.getBoundingClientRect();
                return !!(rect.top || rect.bottom || rect.width || rect.height);
            }
            ''',
            [self]
        )
        return visibility != 'hidden' and has_visible_bounding_box
